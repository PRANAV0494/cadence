/**
 * CADENCE capture SDK
 *
 * Records keystroke timing with a stable per-press identity.
 *
 * WHY THIS EXISTS
 * ---------------
 * The previous implementation (edge/reference/capture.js.BUGGY) identified key
 * events by `input.selectionStart`. The caret sits *before* the inserted
 * character on keydown and *after* it on keyup, so keydown i carried index i
 * while its own keyup carried i+1. Matching on that index paired every keydown
 * with the PREVIOUS character's keyup, producing negative dwell times for 85%
 * of recorded human samples (median -285.5 ms).
 *
 * Caret position is not key identity. Two properties are required:
 *
 *   1. A press must be identifiable independently of document state. Editing,
 *      selection, autocomplete and IME composition all move the caret without
 *      any key being pressed.
 *   2. The identity must survive rollover — a fast typist presses the next key
 *      before releasing the previous one, so presses overlap in time and cannot
 *      be paired by ordering alone.
 *
 * Both are satisfied by assigning each keydown a monotonic sequence number and
 * echoing it on the matching keyup, resolved through a map keyed by the
 * physical key (`event.code`). A key cannot be pressed twice without an
 * intervening release, so `code` is unambiguous for any in-flight press.
 */
(function (global) {
  "use strict";

  const AUTOREPEAT_DROP = true; // held-key repeats are not fresh presses

  function createRecorder() {
    let seq = 0;
    /** code -> seq of the press currently held down */
    const inFlight = new Map();
    const events = [];

    function record(evt) {
      events.push(evt);
      return evt;
    }

    function onKeyDown(e) {
      if (AUTOREPEAT_DROP && e.repeat) return null;

      // A press with no matching release (focus lost mid-press, for example)
      // would otherwise leak its entry and mis-pair a later press of the same
      // key. Overwriting is correct: the stale press can never be released.
      const id = seq++;
      inFlight.set(e.code, id);

      return record({
        event_type: "keydown",
        seq: id,
        code: e.code,
        key: e.key,
        timestamp: performance.now(),
        is_backspace: e.key === "Backspace",
        is_paste: false,
        is_trusted: e.isTrusted,
      });
    }

    function onKeyUp(e) {
      // No matching keydown: the press began before capture started, or the
      // keydown was suppressed. Emit with seq null so the extractor can drop it
      // rather than silently pairing it with an unrelated press.
      const id = inFlight.has(e.code) ? inFlight.get(e.code) : null;
      inFlight.delete(e.code);

      return record({
        event_type: "keyup",
        seq: id,
        code: e.code,
        key: e.key,
        timestamp: performance.now(),
        is_backspace: e.key === "Backspace",
        is_paste: false,
        is_trusted: e.isTrusted,
      });
    }

    function onPaste(e) {
      const text = e.clipboardData ? e.clipboardData.getData("text") : "";
      return record({
        event_type: "keydown",
        seq: seq++,
        code: null,
        key: null,
        timestamp: performance.now(),
        is_backspace: false,
        is_paste: true,
        pasted_length: text.length, // length only — never the content
        is_trusted: e.isTrusted,
      });
    }

    function attach(target) {
      target.addEventListener("keydown", onKeyDown, true);
      target.addEventListener("keyup", onKeyUp, true);
      target.addEventListener("paste", onPaste, true);
      return function detach() {
        target.removeEventListener("keydown", onKeyDown, true);
        target.removeEventListener("keyup", onKeyUp, true);
        target.removeEventListener("paste", onPaste, true);
      };
    }

    return {
      attach: attach,
      onKeyDown: onKeyDown,
      onKeyUp: onKeyUp,
      onPaste: onPaste,
      getEvents: function () {
        return events.slice();
      },
      reset: function () {
        seq = 0;
        inFlight.clear();
        events.length = 0;
      },
      /** Presses still held down. Non-empty at submit time means truncated dwell. */
      pendingCount: function () {
        return inFlight.size;
      },
    };
  }

  const api = { createRecorder: createRecorder };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    global.CadenceSDK = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
