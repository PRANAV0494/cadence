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

  /**
   * Keys that produce no character. They are recorded but flagged, because
   * including them in timing statistics corrupts the result: a Shift held
   * across a capital letter dwells far longer than the letter itself, and
   * counting it as a character inflates typing speed.
   *
   * They are flagged rather than dropped — modifier usage is itself a
   * behavioural signal, and discarding data at capture time is irreversible.
   * Consumers filter on `is_modifier`.
   */
  const MODIFIER_KEYS = new Set([
    "Shift", "Control", "Alt", "Meta", "AltGraph",
    "CapsLock", "NumLock", "ScrollLock",
    "Fn", "FnLock", "Hyper", "Super", "Symbol", "SymbolLock",
  ]);

  /**
   * Other keys that produce no character. Navigation, editing and function keys
   * were previously flagged is_modifier: false, so they entered dwell, typing
   * speed and digraph statistics as if they were typed characters.
   *
   * event.key is a single character for character-producing keys and a named
   * string otherwise, so length > 1 catches the general case; these are listed
   * for clarity and to cover names that are also single characters.
   */
  const NON_CHARACTER_KEYS = new Set([
    "Tab", "Escape", "Enter", "Backspace", "Delete", "Insert",
    "Home", "End", "PageUp", "PageDown",
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    "ContextMenu", "PrintScreen", "Pause", "Clear", "Dead", "Unidentified",
  ]);

  function producesNoCharacter(key) {
    if (typeof key !== "string") return true;
    return (
      MODIFIER_KEYS.has(key) ||
      NON_CHARACTER_KEYS.has(key) ||
      /^F\d{1,2}$/.test(key) ||
      key.length > 1
    );
  }

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
        is_modifier: producesNoCharacter(e.key),
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
        is_modifier: producesNoCharacter(e.key),
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
        is_modifier: false,
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
      drain: function () {
        /**
         * Hand off the buffer for sending and keep recording. Unlike reset(),
         * seq and inFlight survive, so the next event still has a unique id and
         * pairing across a flush boundary stays correct.
         */
        const out = events.slice();
        events.length = 0;
        return out;
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

  /**
   * Send drained events to the proxy's own endpoint. The proxy owns this
   * path; it is never forwarded upstream. `sendBeacon` is preferred because
   * it survives page unload; `fetch` is the fallback for browsers that lack
   * it or reject the payload.
   *
   * Events handed to a sender are never re-drained: a failed send is
   * reported in the return value ({ sent: 0, error: "send-failed" }) and
   * dropped, not retried, because a retry after a partial write could
   * double-count a dwell sample.
   */
  const TELEMETRY_PATH = "/__cadence/telemetry";

  function flush(recorder, transport) {
    const t = transport || {
      beacon: function (url, body) {
        return typeof navigator !== "undefined"
          && typeof navigator.sendBeacon === "function"
          && navigator.sendBeacon(url, body);
      },
      fetchPost: function (url, body) {
        if (typeof fetch !== "function") return false;
        try {
          fetch(url, { method: "POST", body: body, keepalive: true });
          return true;
        } catch (err) {
          return false;
        }
      },
    };

    const events = recorder.drain();
    if (!events.length) return { sent: 0 };
    const body = JSON.stringify({ events: events });
    const url = TELEMETRY_PATH;
    const ok = t.beacon(url, body) || t.fetchPost(url, body);
    return { sent: ok ? events.length : 0, error: ok ? null : "send-failed" };
  }

  const api = { createRecorder: createRecorder, flush: flush, TELEMETRY_PATH: TELEMETRY_PATH };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    global.CadenceSDK = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
