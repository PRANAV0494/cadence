"""mitmproxy addon: inject cadence-sdk.js into HTML responses.

Run via `cadence proxy`, or directly:

    mitmdump -s edge/addon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# edge/ is not an installed package; put it on sys.path so the sibling
# inject module imports regardless of where mitmproxy was launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inject import inject, is_html  # noqa: E402

EDGE_DIR = Path(__file__).resolve().parent
SDK_PATH = EDGE_DIR / "cadence-sdk.js"
SDK_SOURCE = SDK_PATH.read_text(encoding="utf-8")


class CadenceAddon:
    def response(self, flow):
        response = flow.response
        if response is None:
            return
        if not is_html(response.headers.get("content-type", "")):
            return
        body = response.content or b""
        new = inject(body, SDK_SOURCE)
        if new != body:
            response.content = new
            if "Content-Length" in response.headers:
                del response.headers["Content-Length"]


addons = [CadenceAddon()]
