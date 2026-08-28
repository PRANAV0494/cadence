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
  var sendQueue = function (unload) {
    var batch = queue;
    queue = [];
    var ctrl = typeof AbortController === "function" ? new AbortController() : null;
    var timer = ctrl ? window.setTimeout(function () { ctrl.abort(); }, 1500) : null;
    var opts = {
      method: "POST",
      body: JSON.stringify({ events: batch }),
      keepalive: unload === true,
      credentials: "include"
    };
    if (ctrl) opts.signal = ctrl.signal;
    return fetch("/__cadence/telemetry", opts).then(function (res) {
      if (timer !== null) window.clearTimeout(timer);
      if (!res.ok) {
        queue = batch.concat(queue);
        throw new Error("cadence telemetry " + res.status);
      }
    }, function (err) {
      if (timer !== null) window.clearTimeout(timer);
      queue = batch.concat(queue);
      throw err;
    });
  };
  // One batch on the wire at a time, serialized on a chain. Each push()
  // appends its own send, so the returned promise acks everything
  // drained up to THIS call — not merely the batch that happened to be
  // in flight. The abort timer above makes every link settle, so a hung
  // fetch cannot wedge later flushes.
  var chain = Promise.resolve();
  var push = function (unload) {
    var drained = r.drain();
    for (var i = 0; i < drained.length; i++) queue.push(drained[i]);
    var attempt = function () {
      if (queue.length === 0) return undefined;
      return sendQueue(unload);
    };
    chain = chain.then(attempt, attempt);
    return chain;
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
    // Navigate only on an acked flush: submitting after a FAILED flush
    // guarantees a 403 on a buffer the proxy never received. On failure
    // the batch is already re-queued, so retry briefly and otherwise
    // leave the form in place — the interval keeps flushing and the
    // user's next click will find the queue delivered.
    var tries = 6;
    var attempt = function () {
      push(false).then(go, function () {
        tries -= 1;
        if (tries > 0) { window.setTimeout(attempt, 400); }
        else if (window.console && console.warn) {
          console.warn("cadence: telemetry unacknowledged; submit deferred");
        }
      });
    };
    attempt();
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
