"""HTTPS front for the isolated MCP test site; runs inside the fixture tenant container.

Frappe's development server speaks plain HTTP on port 8000. The MCP client requires
verified HTTPS, so this proxy terminates TLS with the local test certificate.
"""

import os
import socket
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPSServer
from typing import override

PORT = int(os.environ["MCP_FIXTURE_TENANT_PORT"])
HOST = f"tenant1.localhost:{PORT}"
HOP_BY_HOP = {"connection", "transfer-encoding", "content-length"}
MAX_BODY = 1_048_576


class Proxy(BaseHTTPRequestHandler):
    @override
    def log_message(self, *args):
        pass

    def forward(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > MAX_BODY:
            self.send_error(413)
            return
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        headers.update({"Host": HOST, "X-Forwarded-Proto": "https"})
        conn = HTTPConnection("127.0.0.1", 8000, timeout=30)
        try:
            conn.request(self.command, self.path, self.rfile.read(size), headers)
            response = conn.getresponse()
            data = response.read()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP_BY_HOP:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        finally:
            conn.close()

    @override
    def do_GET(self):
        self.forward()

    @override
    def do_POST(self):
        self.forward()

    @override
    def do_DELETE(self):
        self.forward()


def main() -> None:
    # Bind to the container's own network address; Compose publishes it only on 127.0.0.1.
    address = socket.gethostbyname(socket.gethostname())
    server = ThreadingHTTPSServer(
        (address, PORT),
        Proxy,
        certfile="/home/frappe/local.crt",
        keyfile="/home/frappe/local.key",
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
