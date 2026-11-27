"""Local G-83 Compose acceptance, using the real Compose configuration reader."""

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "dev/ai-service"


class AIServiceTests(unittest.TestCase):
    def test_database_queue_tls_and_isolation(self):
        result = subprocess.run(
            [
                "docker",
                "--context",
                "colima-factory",
                "compose",
                "-p",
                "fs-ai-service-test",
                "-f",
                str(SETUP / "compose.yaml"),
                "config",
                "--format",
                "json",
            ],
            env=dict(
                os.environ,
                PANE_PORT="7850",
                FS_TENANT_WEB_PORT="8000",
                FS_TENANT_SOCKET_PORT="9000",
                AI_HTTPS_PORT="7850",
                MARIADB_ROOT_PASSWORD="synthetic-test-only",
                ADMIN_PASSWORD="synthetic-test-only",
            ),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        services = config["services"]
        self.assertEqual(
            set(services), {"tenant-db", "tenant-redis", "tenant-web", "tenant-worker", "ai-tls"}
        )
        for name, service in services.items():
            if name != "ai-tls":
                self.assertFalse(service.get("ports"), name)
            for volume in service.get("volumes", []):
                self.assertEqual(volume["type"], "volume", name)
            self.assertNotIn("scheduler", " ".join(service.get("command") or []))
        self.assertEqual(services["ai-tls"]["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(services["ai-tls"]["ports"][0]["target"], 443)
        self.assertIn("worker", services["tenant-worker"]["command"])
        self.assertIn("yes", services["tenant-redis"]["command"])
        caddy = (SETUP / "Caddyfile").read_text()
        self.assertIn("tls internal", caddy)
        self.assertIn("reverse_proxy tenant-web:8000", caddy)
        self.assertIn("Hetzner", config["x-data-residency"]["deployment_target"])
        self.assertFalse(config["x-data-residency"]["conversation_store_implemented"])


if __name__ == "__main__":
    unittest.main()
