"""Pure HTML injection helpers. No mitmproxy import, no I/O, no network."""

from __future__ import annotations

import base64
import hashlib

BOOT_BLOCK = """<script id="cadence-sdk-boot">
(function () {
  if (window.__CADENCE_SDK_LOADED) return;
  window.__CADENCE_SDK_LOADED = true;
  var r = CadenceSDK.createRecorder();
  r.attach(document);
  // Batches that fail to POST go back on this queue: drained keystrokes
  // the proxy never acknowledged must not be lost, or an honest submit
  // 403s on an empty buffer.
  var queue = [];
  var inflight = null;
  var push = function (unload) {
    var drained = r.drain();
    for (var i = 0; i < drained.length; i++) queue.push(drained[i]);
    if (inflight) return inflight;
    if (queue.length === 0) return Promise.resolve();
    var batch = queue;
    queue = [];
    inflight = fetch("/__cadence/telemetry", {
      method: "POST",
      body: JSON.stringify({ events: batch }),
      keepalive: unload === true,
      credentials: "include"
    }).then(function (res) {
      inflight = null;
      if (!res.ok) {
        queue = batch.concat(queue);
        throw new Error("cadence telemetry " + res.status);
      }
    }, function (err) {
      inflight = null;
      queue = batch.concat(queue);
      throw err;
    });
    return inflight;
  };
  window.addEventListener("pagehide", function () { push(true); });
  window.setInterval(function () {
    push(false).then(null, function () {});
  }, 500);
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || (form.tagName || "").toUpperCase() !== "FORM") return;
    if (form.__cadenceResubmitted) {
      delete form.__cadenceResubmitted;
      return;
    }
    // Bubble phase, after the page's own handlers: a form the page
    // cancels (AJAX submit) keeps that behavior untouched.
    if (e.defaultPrevented) return;
    e.preventDefault();
    var submitter = e.submitter;
    var go = function () {
      form.__cadenceResubmitted = true;
      if (typeof form.requestSubmit === "function") {
        if (submitter) { form.requestSubmit(submitter); }
        else { form.requestSubmit(); }
      } else {
        HTMLFormElement.prototype.submit.call(form);
      }
    };
    // A hung telemetry fetch must not wedge the form forever.
    var cap = new Promise(function (resolve) { window.setTimeout(resolve, 2000); });
    Promise.race([push(false), cap]).then(go, go);
  }, false);
})();
</script>"""


def script_bodies(sdk_source: str) -> list[bytes]:
    """The exact content of each injected <script> element, as inject() emits it.

    A CSP hash covers the bytes between the tags — including the newlines
    around the SDK source and inside the boot block. Derived from the same
    constants inject() uses, so the two cannot drift; the test suite pins
    them together by hashing real inject() output.
    """
    boot_inner = BOOT_BLOCK.encode("utf-8")
    open_end = boot_inner.index(b">") + 1
    close_start = boot_inner.rindex(b"</script>")
    return [
        b"\n" + sdk_source.encode("utf-8") + b"\n",
        boot_inner[open_end:close_start],
    ]


def csp_hashes(sdk_source: str) -> list[str]:
    """Quoted sha256 CSP hash tokens for both injected scripts, in order.

    CSP grammar requires the single quotes: 'sha256-<b64>'. Unquoted, the
    token is ignored and the script stays blocked.
    """
    tokens = []
    for body in script_bodies(sdk_source):
        digest = hashlib.sha256(body).digest()
        tokens.append("'sha256-" + base64.b64encode(digest).decode("ascii") + "'")
    return tokens


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
