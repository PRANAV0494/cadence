"""Pure HTML injection helpers. No mitmproxy import, no I/O, no network."""

from __future__ import annotations

BOOT_BLOCK = """<script id="cadence-sdk-boot">
(function () {
  if (window.__CADENCE_SDK_LOADED) return;
  window.__CADENCE_SDK_LOADED = true;
  var r = CadenceSDK.createRecorder();
  r.attach(document);
  var send = function () { CadenceSDK.flush(r); };
  window.addEventListener("pagehide", send);
  window.setInterval(send, 5000);
})();
</script>"""


def is_html(content_type: str | None) -> bool:
    """True iff content_type contains text/html, case-insensitive. None/empty → False."""
    if not content_type:
        return False
    return "text/html" in content_type.lower()


def already_injected(html: bytes) -> bool:
    """True iff html already contains id="cadence-sdk" or id='cadence-sdk'."""
    return (
        b'id="cadence-sdk"' in html
        or b"id='cadence-sdk'" in html
    )


def inject(html: bytes, sdk_source: str) -> bytes:
    if already_injected(html):
        return html
    marker = b"</body>"
    lowered = html.lower()
    idx = lowered.rfind(marker)
    if idx == -1:
        return html
    block = (
        b'<script id="cadence-sdk">\n'
        + sdk_source.encode("utf-8")
        + b"\n</script>\n"
        + BOOT_BLOCK.encode("utf-8")
        + b"\n"
    )
    # rfind on the lowercase page finds the last </body> at the same offset
    # in the original bytes; splice ahead of it unchanged.
    return html[:idx] + block + html[idx:]
