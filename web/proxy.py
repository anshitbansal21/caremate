#!/usr/bin/env python3
"""CareMate web console — local proxy + static server (demo fallback client).

Serves web/index.html and reverse-proxies /api/* to the hub's HttpAppBus
(docs/app-api.md). Runs on a laptop on the same hotspot as the hub. Purpose:

- Same-origin: the browser talks to THIS server, so EventSource(/api/events),
  fetch POSTs, and the MJPEG feed all work without the hub sending CORS headers
  (it only sets CORS on /frame).
- Token stays here: the hub bearer token is injected server-side, never shipped
  to browser JS.
- Streaming-safe: a raw-socket relay pipes SSE and MJPEG through unbuffered.

Touches no hub code. Config via env:
    HUB_HOST (default 172.20.10.2)   HUB_PORT (default 8080)
    CAREMATE_TOKEN (default caremate-dev)   PORT (this server, default 8090)

Run:  python3 web/proxy.py     then open  http://localhost:8090
"""

from __future__ import annotations

import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HUB_HOST = os.environ.get("HUB_HOST", "172.20.10.2")
HUB_PORT = int(os.environ.get("HUB_PORT", "8080"))
TOKEN = os.environ.get("CAREMATE_TOKEN", "caremate-dev")
LISTEN_PORT = int(os.environ.get("PORT", "8090"))

_HERE = os.path.dirname(os.path.abspath(__file__))
_INDEX = os.path.join(_HERE, "index.html")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # quiet
        return

    # -- routing ------------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._serve_index()
        if self.path.startswith("/api/"):
            return self._relay("GET")
        return self._simple(404, b"not found")

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._relay("POST")
        return self._simple(404, b"not found")

    # -- static -------------------------------------------------------------
    def _serve_index(self):
        try:
            with open(_INDEX, "rb") as f:
                body = f.read()
        except OSError:
            return self._simple(500, b"index.html missing")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _simple(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    # -- reverse proxy (raw relay) ------------------------------------------
    def _relay(self, method):
        hub_path = self.path[len("/api"):]  # keep query string, strip /api prefix
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""

        try:
            up = socket.create_connection((HUB_HOST, HUB_PORT), timeout=8)
        except OSError:
            return self._simple(502, b'{"error":"hub unreachable"}')

        # Connection: close makes the hub end the response by closing the
        # socket, so the read-until-EOF relay below works uniformly for both
        # streaming (SSE/MJPEG, no Content-Length) and normal responses.
        req = (
            f"{method} {hub_path} HTTP/1.1\r\n"
            f"Host: {HUB_HOST}:{HUB_PORT}\r\n"
            f"Authorization: Bearer {TOKEN}\r\n"
            f"Connection: close\r\n"
        )
        if body:
            req += "Content-Type: application/json\r\n"
            req += f"Content-Length: {len(body)}\r\n"
        req += "\r\n"

        self.close_connection = True  # we forward a raw response; don't reuse
        try:
            up.sendall(req.encode() + body)
            up.settimeout(None)
            while True:
                chunk = up.recv(4096)
                if not chunk:
                    break
                self.wfile.write(chunk)  # raw hub response (status+headers+body)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            try:
                up.close()
            except OSError:
                pass


def main():
    server = ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Handler)
    server.daemon_threads = True
    print(f"CareMate web console on http://localhost:{LISTEN_PORT}")
    print(f"  proxying /api/* -> hub {HUB_HOST}:{HUB_PORT} (token: {'set' if TOKEN else 'none'})")
    print("  open the URL above in a browser on the same hotspot. Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
