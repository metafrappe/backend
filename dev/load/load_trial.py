"""G-149 load trial: send a short burst of requests to a local site and report p50, p75 and p95.

The numbers are an experiment, not measured capacity or a product promise (G-149).
The script reaches only local addresses: localhost, 127.0.0.1, ::1 and *.localhost.
A load trial on a live server is a DevOps task and needs its own approval.

Examples:
    python3 dev/load/load_trial.py --self-test
    python3 dev/load/load_trial.py --base-url http://127.0.0.1:8000 --site tenant1.localhost \
        --path /api/method/ping --requests 50 --concurrency 4
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import ceil
from threading import Thread
from time import perf_counter
from urllib.parse import urlsplit

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
MAX_REQUESTS = 10_000
MAX_CONCURRENCY = 32


def percentile(values, rank):
    """Nearest-rank percentile. Returns None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(ceil(rank / 100 * len(ordered)), 1) - 1]


def server_duration(header):
    """Read the `app` duration in milliseconds from a Server-Timing header."""
    for entry in (header or "").split(","):
        name, _separator, params = entry.strip().partition(";")
        if name != "app":
            continue
        for param in params.split(";"):
            key, _equals, value = param.strip().partition("=")
            if key == "dur":
                try:
                    return float(value)
                except ValueError:
                    return None
    return None


def local_target(base_url):
    parts = urlsplit(base_url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "http" or not (host in LOCAL_HOSTS or host.endswith(".localhost")):
        return None
    return host, parts.port or 80


def one_request(host, port, path, site):
    headers = {"X-Frappe-Site-Name": site} if site else {}
    connection = HTTPConnection(host, port, timeout=30)
    started = perf_counter()
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        response.read()
        status = response.status
        timing = response.getheader("Server-Timing")
    except OSError:
        status, timing = None, None
    finally:
        connection.close()
    return status, (perf_counter() - started) * 1000, server_duration(timing)


def summary(values):
    return {
        "p50_ms": round(percentile(values, 50), 1) if values else None,
        "p75_ms": round(percentile(values, 75), 1) if values else None,
        "p95_ms": round(percentile(values, 95), 1) if values else None,
    }


def run_trial(base_url, paths, requests, concurrency, site=None):
    host, port = local_target(base_url)
    report = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for path in paths:
            results = list(pool.map(lambda _index: one_request(host, port, path, site), range(requests)))
            ok = [result for result in results if result[0] is not None and 200 <= result[0] < 400]
            server = [result[2] for result in ok if result[2] is not None]
            report[path] = {
                "requests": requests,
                "concurrency": concurrency,
                "errors": requests - len(ok),
                "client": summary([result[1] for result in ok]),
                "server": summary(server),
                "server_timing_missing": len(ok) - len(server),
            }
    return report


class SelfTestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"message": "pong"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Server-Timing", "app;dur=1.5")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def self_test():
    """Run a short trial against a stand-in server on 127.0.0.1. It checks the script only."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), SelfTestHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        return run_trial(f"http://127.0.0.1:{server.server_port}", ["/api/method/ping"], 20, 4)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--site", help="Frappe site name, sent as X-Frappe-Site-Name.")
    parser.add_argument("--path", action="append", dest="paths", help="Path to request. Repeat for more.")
    parser.add_argument("--requests", type=int, default=50, help="Requests per path.")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--self-test", action="store_true", help="Run against a stand-in local server.")
    args = parser.parse_args(argv)
    if args.self_test:
        report = self_test()
    else:
        if local_target(args.base_url) is None:
            print("Only local http targets are allowed: localhost, 127.0.0.1, ::1 or *.localhost.", file=sys.stderr)
            return 2
        if not 1 <= args.requests <= MAX_REQUESTS or not 1 <= args.concurrency <= MAX_CONCURRENCY:
            print(f"Use 1-{MAX_REQUESTS} requests and 1-{MAX_CONCURRENCY} parallel requests.", file=sys.stderr)
            return 2
        report = run_trial(args.base_url, args.paths or ["/api/method/ping"], args.requests, args.concurrency, args.site)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if any(entry["errors"] for entry in report.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
