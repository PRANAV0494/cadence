"""Demo form: GET is a message field, POST returns a complete body."""

import http.client
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cadence.demo import FORM_HTML, OK_HTML, bind_form_server, serve_in_thread  # noqa: E402


def test_form_html_uses_the_gated_field_name():
    assert b'name="message"' in FORM_HTML
    assert b"<form" in FORM_HTML


def test_get_and_post_return_full_bodies():
    httpd = bind_form_server("127.0.0.1")
    serve_in_thread(httpd)
    host, port = httpd.server_address[:2]
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/")
        got = conn.getresponse()
        body = got.read()
        assert got.status == 200
        assert b'name="message"' in body
        conn.close()

        conn = http.client.HTTPConnection(host, port, timeout=5)
        payload = b"message=hi"
        conn.request(
            "POST",
            "/submit",
            body=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(payload)),
            },
        )
        posted = conn.getresponse()
        out = posted.read()
        assert posted.status == 200
        assert out == OK_HTML
        assert int(posted.getheader("Content-Length")) == len(OK_HTML)
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
