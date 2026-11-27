"""Isolated local Keycloak + Frappe fixture for the MCP OAuth client.

The fixture is a separate Compose project. It never builds, pulls, restarts or reads the
shared development stack. Secrets live only in a 0600 file outside the repository.

Commands:
  prepare        Create secrets, realm copy, test certificate and Compose file.
  up             Start the fixture, seed the test site and wait until both services answer.
  password-file  Print the path of the file that holds the sample account password.
  run            Run client.py against the fixture with the password from that file.
  test           Run the offline unit tests.
  lock -- CMD    Run any command while holding the shared test lock.
  status         Show the fixture containers.
  down           Remove the fixture containers; keep the data volumes.
"""

import argparse
import contextlib
import fcntl
import http.client
import io
import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import subprocess
import sys
import tarfile
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PROJECT = "fs-mcp-oauth"
BASE_PORT = 7840
USERNAME = "mcp-e2e-reader@example.test"
DEFAULT_TENANT_IMAGE = "fs-tenant-dev:fs-e2e-7400-d048900ff39946fe9a1d"
DEFAULT_KEYCLOAK_IMAGE = "fs-keycloak-atonota:dev-fs-e2e-7400-d048900ff39946fe9a1d"
MCP_PATH = "/api/method/platform_core.api.ai.mcp"
SECRET_KEYS = ("password", "introspection_secret", "db_root", "admin")
PLACEHOLDER = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?::([^}]*))?\}")
DEFAULT_SUBNET = "10.217.58.0/24"


def endpoints(base: int = BASE_PORT) -> dict:
    return {
        "keycloak_port": base,
        "tenant_port": base + 1,
        "callback_port": base + 2,
        "resource": f"https://tenant1.localhost:{base + 1}{MCP_PATH}",
        "issuer": f"https://identity.localhost:{base}/realms/platform",
        "keycloak_url": f"https://identity.localhost:{base}",
        "callback": f"http://127.0.0.1:{base + 2}/callback",
    }


RESOURCE = endpoints()["resource"]


def fail(message: str, code: int = 2):
    print(message, file=sys.stderr)
    raise SystemExit(code)


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Single process entry point; callers pass fixed argument lists, never a shell string."""
    return subprocess.run(args, **kwargs)


def docker_context(env) -> str:
    profile = env.get("FS_COLIMA_PROFILE", "factory")
    contexts = {"factory": "colima-factory", "default": "colima"}
    if profile not in contexts:
        fail("FS_COLIMA_PROFILE must be factory or default.")
    return contexts[profile]


def docker(env, *args: str, **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("check", True)
    return run(["docker", "--context", docker_context(env), *args], **kwargs)


def state_dir(env) -> Path:
    raw = env.get("MCP_FIXTURE_DIR") or str(
        Path(env.get("HOME", str(Path.home()))) / ".cache/frappesetup/mcp-oauth-fixture"
    )
    path = Path(raw)
    if not path.is_absolute():
        fail("MCP_FIXTURE_DIR must be an absolute path.")
    resolved = path.resolve()
    if resolved == REPO or REPO in resolved.parents:
        fail("MCP_FIXTURE_DIR must be outside the Git repository; it holds secrets.")
    return path


def lock_path(env) -> Path:
    default = Path(env.get("HOME", str(Path.home()))) / ".cache/frappesetup/mcp-oauth.lock"
    return Path(env.get("MCP_FIXTURE_LOCK") or default)


@contextlib.contextmanager
def test_lock(path: Path, owner: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.seek(0)
            holder = handle.read().strip() or "unknown"
            print(f"The shared MCP test lock is held by: {holder}", file=sys.stderr)
            raise SystemExit(f"Locked by {holder}; wait for it to finish.") from None
        handle.seek(0)
        handle.truncate()
        handle.write(f"{owner} pid={os.getpid()}\n")
        handle.flush()
        try:
            yield
        finally:
            handle.seek(0)
            handle.truncate()
            fcntl.flock(handle, fcntl.LOCK_UN)


def new_values(base: int = BASE_PORT) -> dict:
    return {
        **endpoints(base),
        "project": PROJECT,
        "username": USERNAME,
        "subject": str(uuid.uuid4()),
        "password": secrets.token_urlsafe(32) + "Aa9!",
        "introspection_secret": secrets.token_urlsafe(32),
        "db_root": secrets.token_urlsafe(32),
        "admin": secrets.token_urlsafe(32),
    }


def build_realm(source: str, values: dict) -> dict:
    known = {
        "ATONOTA_MCP_RESOURCE_URL": values["resource"],
        "ATONOTA_MCP_REDIRECT_URI": values["callback"],
        "ATONOTA_MCP_INTROSPECTION_SECRET": values["introspection_secret"],
        "ATONOTA_SSL_REQUIRED": "all",
    }

    def substitute(match: re.Match) -> str:
        key, default = match[1], match[2]
        if key not in known:
            # Unused integrations get inert values; their clients and providers stay off.
            known[key] = default or (
                "https://unused.example.test" if key.endswith("URL") else secrets.token_urlsafe(24)
            )
        return known[key]

    realm = json.loads(PLACEHOLDER.sub(substitute, source))
    for client in realm["clients"]:
        if client["clientId"] in {"mcp-external", "mcp-resource", values["resource"]}:
            client["enabled"] = True
    realm["eventsListeners"] = []
    realm["identityProviders"] = []
    realm["smtpServer"] = {}
    realm["users"] = [
        {
            "id": values["subject"],
            "username": values["username"],
            "email": values["username"],
            "emailVerified": True,
            "enabled": True,
            "firstName": "MCP",
            "lastName": "Fixture",
            "requiredActions": [],
            "credentials": [{"type": "password", "value": values["password"], "temporary": False}],
        }
    ]
    return realm


def site_config(values: dict) -> dict:
    return {
        "mcp_oauth_enabled": 1,
        "mcp_oauth_resource": values["resource"],
        "mcp_oauth_client_ids": ["mcp-external"],
        "mcp_oauth_introspection_secret": values["introspection_secret"],
        "keycloak_public_url": values["keycloak_url"],
        "keycloak_internal_url": values["keycloak_url"],
        "keycloak_realm": "platform",
        "host_name": f"https://tenant1.localhost:{values['tenant_port']}",
        "developer_mode": 1,
        "mute_emails": 1,
        "kimlik_deletion_hmac_key": secrets.token_urlsafe(32),
    }


def certificate() -> tuple[bytes, bytes]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "MCP OAuth local test")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(n) for n in ("identity.localhost", "tenant1.localhost")]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


def compose_file(values: dict, tenant_image: str, keycloak_image: str, subnet: str) -> dict:
    kc, tenant = values["keycloak_port"], values["tenant_port"]
    return {
        "name": values["project"],
        "services": {
            "db": {
                "image": "mariadb:11.8.9",
                "environment": {"MARIADB_ROOT_PASSWORD": values["db_root"]},
                "volumes": ["db:/var/lib/mysql"],
                "command": ["--character-set-server=utf8mb4", "--collation-server=utf8mb4_unicode_ci"],
            },
            "redis": {
                "image": "redis:7.4-alpine",
                "command": ["redis-server", "--save", "", "--appendonly", "no"],
            },
            "keycloak": {
                "image": keycloak_image,
                "command": [
                    "start-dev",
                    "--import-realm",
                    "--features=resource-indicators",
                    "--http-enabled=false",
                    f"--https-port={kc}",
                    "--https-certificate-file=/opt/keycloak/local.crt",
                    "--https-certificate-key-file=/opt/keycloak/local.key",
                    f"--hostname={values['keycloak_url']}",
                ],
                "networks": {"default": {"aliases": ["identity.localhost"]}},
                "ports": [f"127.0.0.1:{kc}:{kc}"],
                "volumes": ["keycloak:/opt/keycloak/data/h2"],
            },
            "tenant": {
                "image": tenant_image,
                "command": ["sleep", "infinity"],
                "environment": {
                    "SSL_CERT_FILE": "/home/frappe/local.crt",
                    "MCP_FIXTURE_TENANT_PORT": str(tenant),
                },
                "volumes": ["sites:/home/frappe/frappe-bench/sites", "logs:/home/frappe/frappe-bench/logs"],
                "ports": [f"127.0.0.1:{tenant}:{tenant}"],
                "networks": {"default": {"aliases": ["tenant1.localhost"]}},
            },
        },
        "volumes": {name: {} for name in ("db", "keycloak", "sites", "logs")},
        # Docker's default address pools can be exhausted; a fixed private subnet avoids that.
        "networks": {"default": {"ipam": {"config": [{"subnet": subnet}]}}},
    }


def write_private(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def prepare(directory: Path, repo: Path, env=None) -> None:
    env = os.environ if env is None else env
    if (directory / "fixture.json").exists():
        fail(f"{directory}/fixture.json already exists; secrets are never overwritten.")
    base = int(env.get("MCP_FIXTURE_PORT", BASE_PORT))
    if not 1024 <= base <= 65530:
        fail("MCP_FIXTURE_PORT must be between 1024 and 65530.")
    subnet = env.get("MCP_FIXTURE_SUBNET", DEFAULT_SUBNET)
    try:
        network = ipaddress.ip_network(subnet)
    except ValueError:
        fail("MCP_FIXTURE_SUBNET must be a private IPv4 network such as 10.217.58.0/24.")
    if not (network.version == 4 and network.is_private and 16 <= network.prefixlen <= 28):
        fail("MCP_FIXTURE_SUBNET must be a private IPv4 network such as 10.217.58.0/24.")
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    values = new_values(base)
    realm = build_realm((repo / "identity/keycloak/realm/platform-realm.json").read_text(), values)
    crt, key = certificate()
    compose = compose_file(
        values,
        env.get("MCP_FIXTURE_TENANT_IMAGE", DEFAULT_TENANT_IMAGE),
        env.get("MCP_FIXTURE_KEYCLOAK_IMAGE", DEFAULT_KEYCLOAK_IMAGE),
        str(network),
    )
    write_private(directory / "platform-realm.json", json.dumps(realm).encode())
    write_private(
        directory / "platform-users-0.json", json.dumps({"realm": "platform", "users": []}).encode()
    )
    write_private(directory / "local.key", key)
    write_private(directory / "compose.json", json.dumps(compose, indent=1).encode())
    (directory / "local.crt").write_bytes(crt)
    write_private(directory / "fixture.json", json.dumps(values, indent=1).encode())
    print(f"Prepared {directory}. The password is in {directory / 'fixture.json'} (key: password).")


def load(directory: Path) -> dict:
    path = directory / "fixture.json"
    if not path.exists():
        fail(f"{path} is missing. Run the prepare command first.")
    return json.loads(path.read_text())


def compose_create_args() -> list[str]:
    return ["create", "--pull", "never"]


def compose(env, directory: Path, *args: str, **kwargs):
    return docker(env, "compose", "-f", str(directory / "compose.json"), *args, **kwargs)


def running_containers(env, project: str) -> list[str]:
    out = docker(
        env,
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.compose.project={project}",
        capture_output=True,
        text=True,
    )
    return out.stdout.split()


def port_owners(env, ports: list[int]) -> list[str]:
    names = []
    for port in ports:
        out = docker(
            env, "ps", "--format", "{{.Names}}", "--filter", f"publish={port}", capture_output=True, text=True
        )
        names += out.stdout.split()
    return names


def copy_in(env, container: str, dest: str, files: dict[str, bytes], uid: int = 1000) -> None:
    """Stream files as a tar so private host files stay 0600; the container user can read them."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.uid, info.gid = len(data), 0o640, uid, 0
            tar.addfile(info, io.BytesIO(data))
    docker(env, "cp", "-a", "-", f"{container}:{dest}", input=buffer.getvalue())


def wait_https(url: str, cafile: Path, deadline: float, accept=(200,)) -> None:
    host, _, rest = url.removeprefix("https://").partition("/")
    hostname, _, port = host.partition(":")
    context = ssl.create_default_context(cafile=str(cafile))
    while True:
        try:
            conn = http.client.HTTPSConnection(hostname, int(port), context=context, timeout=5)
            conn.request("GET", "/" + rest)
            status = conn.getresponse().status
            conn.close()
            if status in accept:
                return
        except (OSError, http.client.HTTPException):
            pass
        if time.monotonic() > deadline:
            fail(f"{url} did not answer in time. Check the container logs.", 1)
        time.sleep(3)


def reachable(port: int) -> bool:
    with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", port), timeout=2):
        return True
    return False


def open_tunnel(env, directory: Path, ports: list[int]) -> None:
    """Colima may not forward ports; open a task-only SSH forward for exactly these ports."""
    if all(reachable(p) for p in ports):
        return
    lima = docker_context(env)
    config = Path(env.get("HOME", str(Path.home()))) / f".colima/_lima/{lima}/ssh.config"
    if not config.exists():
        fail(f"Ports {ports} are not reachable and {config} is missing.", 1)
    forwards = [arg for p in ports for arg in ("-L", f"127.0.0.1:{p}:127.0.0.1:{p}")]
    run(
        [
            "ssh",
            "-F",
            str(config),
            "-o",
            f"ControlPath={directory / 'tunnel.sock'}",
            "-o",
            "ExitOnForwardFailure=yes",
            "-M",
            "-f",
            "-N",
            *forwards,
            f"lima-{lima}",
        ],
        check=True,
    )


def close_tunnel(env, directory: Path) -> None:
    sock = directory / "tunnel.sock"
    if sock.exists():
        lima = docker_context(env)
        config = Path(env.get("HOME", str(Path.home()))) / f".colima/_lima/{lima}/ssh.config"
        run(
            ["ssh", "-F", str(config), "-o", f"ControlPath={sock}", "-O", "exit", f"lima-{lima}"], check=False
        )


def up(directory: Path, repo: Path, env) -> None:
    values = load(directory)
    project = values["project"]
    ports = [values["keycloak_port"], values["tenant_port"]]
    if running_containers(env, project):
        fail(f"{project} is already running; nothing was changed.", 0)
    taken = port_owners(env, ports)
    if taken:
        fail(f"Ports {ports} are used by {', '.join(taken)}. Stop that fixture first; nothing was changed.")
    keycloak, tenant = f"{project}-keycloak-1", f"{project}-tenant-1"
    compose(env, directory, *compose_create_args())
    # A fresh named volume is root-owned; Keycloak runs as uid 1000 and must write its H2 file.
    compose(
        env, directory, "run", "--rm", "--no-deps", "--pull", "never", "-u", "0",
        "--entrypoint", "chown", "keycloak", "1000:0", "/opt/keycloak/data/h2",
    )  # fmt: skip
    tls = {
        "local.crt": (directory / "local.crt").read_bytes(),
        "local.key": (directory / "local.key").read_bytes(),
    }
    copy_in(env, keycloak, "/opt/keycloak", tls)
    copy_in(
        env,
        keycloak,
        "/opt/keycloak/data/import",
        {name: (directory / name).read_bytes() for name in ("platform-realm.json", "platform-users-0.json")},
    )
    copy_in(
        env,
        tenant,
        "/home/frappe",
        {
            **tls,
            "fixture_seed.py": (HERE / "fixture_seed.py").read_bytes(),
            "fixture_tls_proxy.py": (HERE / "fixture_tls_proxy.py").read_bytes(),
        },
    )
    compose(env, directory, "start")
    app = "/home/frappe/frappe-bench/apps/platform_core"
    docker(env, "exec", "-u", "0", tenant, "rm", "-rf", app)
    docker(env, "cp", str(repo / "apps/platform_core"), f"{tenant}:{app}")
    docker(env, "exec", "-u", "0", tenant, "chown", "-R", "1000:0", app)
    deadline = time.monotonic() + 120
    while docker(
        env, "exec", f"{project}-db-1", "mariadb-admin", "ping", "--silent", check=False, capture_output=True
    ).returncode:
        if time.monotonic() > deadline:
            fail("MariaDB did not start in time.", 1)
        time.sleep(3)
    settings = {
        "db_root": values["db_root"],
        "admin": values["admin"],
        "site_config": site_config(values),
        "identity": {
            "issuer": values["issuer"],
            "subject": values["subject"],
            "email": values["username"],
            "email_verified": True,
            "enabled": True,
            "first_name": "MCP",
        },
    }
    docker(
        env,
        "exec",
        "-i",
        "-w",
        "/home/frappe/frappe-bench",
        tenant,
        "env/bin/python",
        "/home/frappe/fixture_seed.py",
        input=json.dumps(settings).encode(),
    )
    for command in (
        "bench serve --port 8000 --noreload > /home/frappe/bench.log 2>&1",
        "env/bin/python /home/frappe/fixture_tls_proxy.py > /home/frappe/proxy.log 2>&1",
    ):
        docker(env, "exec", "-d", "-w", "/home/frappe/frappe-bench", tenant, "sh", "-c", command)
    open_tunnel(env, directory, ports)
    deadline = time.monotonic() + 240
    wait_https(values["issuer"] + "/.well-known/openid-configuration", directory / "local.crt", deadline)
    wait_https(
        f"https://tenant1.localhost:{values['tenant_port']}/api/method/ping",
        directory / "local.crt",
        deadline,
    )
    print(f"{project} is ready. Keycloak: {values['keycloak_url']}  MCP: {values['resource']}")


def down(directory: Path, env) -> None:
    values = load(directory)
    compose(env, directory, "down")
    close_tunnel(env, directory)
    print(f"{values['project']} containers were removed. Data volumes were kept.")


def client_command(directory: Path, values: dict, python: str) -> list[str]:
    return [
        python, str(HERE / "client.py"),
        "--resource", values["resource"],
        "--issuer", values["issuer"],
        "--callback", values["callback"],
        "--username", values["username"],
        "--ca-file", str(directory / "local.crt"),
    ]  # fmt: skip


def main(argv=None, env=None) -> int:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "command", choices=["prepare", "up", "password-file", "run", "test", "lock", "status", "down"]
    )
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    directory = state_dir(env)
    if args.command == "prepare":
        prepare(directory, REPO, env)
        return 0
    if args.command == "password-file":
        load(directory)
        print(directory / "fixture.json")
        return 0
    if args.command == "status":
        return compose(env, directory, "ps", check=False).returncode
    owner = env.get("MCP_LOCK_OWNER", "")
    if not re.fullmatch(r"[A-Z]+-[0-9]+", owner):
        fail("Set MCP_LOCK_OWNER to your task id, for example AJA-1658.")
    with test_lock(lock_path(env), owner):
        if args.command == "up":
            up(directory, REPO, env)
            return 0
        if args.command == "down":
            down(directory, env)
            return 0
        if args.command == "test":
            return run(
                [sys.executable, "-B", "-m", "unittest", "discover", "-s", str(HERE / "tests")]
            ).returncode
        if args.command == "run":
            values = load(directory)
            child = {**env, "MCP_TEST_PASSWORD": values["password"]}
            return run(client_command(directory, values, sys.executable), env=child, cwd=REPO).returncode
        rest = args.rest[1:] if args.rest[:1] == ["--"] else args.rest
        if not rest:
            fail("Usage: fixture.py lock -- COMMAND [ARGS]")
        return run(rest).returncode


if __name__ == "__main__":
    raise SystemExit(main())
