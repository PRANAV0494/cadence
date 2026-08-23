/**
 * Keystroke Dynamics SDK — Silent Continuous Capture
 * Injected by Burp Suite into every HTML page.
 * Captures keydown/keyup timings, computes digraph features,
 * and sends to the analyzer backend every N keystrokes.
 *
 * Self-Aware Hybrid Threat Analyzer
 */
(function () {
    "use strict";

    // Prevent double-injection
    if (window.__KS_SDK_LOADED) return;
    window.__KS_SDK_LOADED = true;

    // ── Config ──────────────────────────────────────────────
    var API_URL = "http://127.0.0.1:8000/keystroke_freeform";
    var BATCH_SIZE = 50;       // send every N key-release events
    var USER_ID = "burp_user"; // default; backend can override

    // ── State ───────────────────────────────────────────────
    var keyDownTimes = {};  // key -> timestamp (ms)
    var events = [];        // {key, downTime, upTime}
    var prevUp = 0;         // timestamp of previous key-up
    var prevDown = 0;       // timestamp of previous key-down

    // Digraph accumulators
    var holdTimes = [];
    var flightTimes = [];   // up-down (UD) between consecutive keys
    var ddTimes = [];       // down-down between consecutive keys
    var keyCount = 0;

    // ── Capture engine ─────────────────────────────────────
    document.addEventListener("keydown", function (e) {
        // Skip modifier keys, function keys, navigation
        if (e.key.length > 1 && !["Shift", "Backspace", "Enter", " "].includes(e.key)) return;

        var now = performance.now();
        var k = e.key.toLowerCase();

        // Avoid repeat events from held keys
        if (keyDownTimes[k]) return;
        keyDownTimes[k] = now;

        // DD time (down-down)
        if (prevDown > 0) {
            ddTimes.push((now - prevDown) / 1000);
        }
        prevDown = now;
    }, true);

    document.addEventListener("keyup", function (e) {
        var now = performance.now();
        var k = e.key.toLowerCase();
        var downTime = keyDownTimes[k];
        if (!downTime) return;
        delete keyDownTimes[k];

        // Hold time (key held down)
        var hold = (now - downTime) / 1000;
        holdTimes.push(hold);

        // Flight time / UD (time from prev key-up to this key-down)
        if (prevUp > 0) {
            flightTimes.push((downTime - prevUp) / 1000);
        }
        prevUp = now;

        keyCount++;

        // Check if batch is ready
        if (keyCount >= BATCH_SIZE) {
            sendBatch();
        }
    }, true);

    // ── Feature computation ────────────────────────────────
    function mean(arr) {
        if (!arr.length) return 0;
        var s = 0;
        for (var i = 0; i < arr.length; i++) s += arr[i];
        return s / arr.length;
    }

    function std(arr) {
        if (arr.length < 2) return 0;
        var m = mean(arr);
        var s = 0;
        for (var i = 0; i < arr.length; i++) s += (arr[i] - m) * (arr[i] - m);
        return Math.sqrt(s / arr.length);
    }

    function maxArr(arr) {
        if (!arr.length) return 0;
        var mx = arr[0];
        for (var i = 1; i < arr.length; i++) if (arr[i] > mx) mx = arr[i];
        return mx;
    }

    function minArr(arr) {
        if (!arr.length) return 0;
        var mn = arr[0];
        for (var i = 1; i < arr.length; i++) if (arr[i] < mn) mn = arr[i];
        return mn;
    }

    function buildFeatures() {
        return {
            hold_mean: mean(holdTimes),
            hold_std: std(holdTimes),
            flight_mean: mean(flightTimes),
            flight_std: std(flightTimes),
            dd_mean: mean(ddTimes),
            dd_std: std(ddTimes),
            typing_speed: keyCount > 0 ? keyCount / (mean(ddTimes) * keyCount || 1) : 0,
            hold_max: maxArr(holdTimes),
            hold_min: minArr(holdTimes),
            flight_max: maxArr(flightTimes),
            flight_min: minArr(flightTimes),
            dd_max: maxArr(ddTimes),
            dd_min: minArr(ddTimes),
            consistency: mean(holdTimes) > 0 ? std(holdTimes) / mean(holdTimes) : 0,
            sample_size: keyCount,
        };
    }

    // ── Send to backend ────────────────────────────────────
    function sendBatch() {
        if (holdTimes.length < 5) {
            resetAccumulators();
            return;
        }

        var features = buildFeatures();

        var payload = {
            user_id: USER_ID,
            features: features,
            page_url: window.location.href,
            timestamp: new Date().toISOString(),
        };

        // Use sendBeacon for non-blocking, or fall back to fetch
        try {
            var blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
            if (navigator.sendBeacon) {
                navigator.sendBeacon(API_URL, blob);
            } else {
                fetch(API_URL, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                    keepalive: true,
                }).catch(function () { }); // silent fail
            }
        } catch (e) {
            // SDK must never break the host page
        }

        resetAccumulators();
    }

    function resetAccumulators() {
        holdTimes = [];
        flightTimes = [];
        ddTimes = [];
        keyCount = 0;
    }
})();
