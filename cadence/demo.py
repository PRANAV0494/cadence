"""In-process demo form served behind `cadence demo` reverse mode.

Normal browsers open the reverse-proxy URL. This server is the upstream
the proxy forwards to; it is not itself the public port.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

FORM_HTML = b"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>cadence demo</title></head>
<body style="font-family:sans-serif;max-width:40rem;margin:2rem">
<h1>Cadence demo</h1>
<p>Type in the box, then click submit. Do not press Enter in the box.</p>
<form method="POST" action="/submit">
<textarea name="message" rows="6" cols="50" placeholder="type here"></textarea><br>
<button type="submit">submit</button>
</form>
<p><a href="/__cadence/console">live console</a></p>
</body>
</html>
"""

OK_HTML = b"""<!doctype html>
<html>
<head><meta charset="utf-8"><title>cadence demo</title></head>
<body style="font-family:sans-serif;max-width:40rem;margin:2rem">
<h1 style="color:green">Cadence allowed this submit</h1>
<p>The website received your form. Provenance matched your keystrokes.</p>
<p><a href="/">Try again</a></p>
</body>
</html>
"""


class DemoHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        return

    def _send(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def do_GET(self) -> None:
        self._send(FORM_HTML, "text/html; charset=utf-8")

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        self._send(OK_HTML, "text/html; charset=utf-8")


def bind_form_server(host: str = "127.0.0.1") -> HTTPServer:
    """Listen on an ephemeral loopback port; caller reads server_address."""
    return HTTPServer((host, 0), DemoHandler)


def serve_in_thread(httpd: HTTPServer) -> Thread:
    t = Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return t
