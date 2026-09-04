"""mitmproxy addon: inject cadence-sdk.js into HTML responses, receive its telemetry.

Run via `cadence proxy`, or directly:

    mitmdump -s edge/addon.py
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

# edge/ is not an installed package; put it on sys.path so the sibling
# modules import regardless of where mitmproxy was launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from automation import is_automated  # noqa: E402
from console import (  # noqa: E402
    CONSOLE_PATH,
    CONSOLE_STATE_PATH,
    PAGE,
    replace_state_path,
    snapshot,
)
from dump import append_flush  # noqa: E402
from drift import drift_signal  # noqa: E402
from fusion import update as fusion_update  # noqa: E402
from inject import csp_hashes, inject, is_html  # noqa: E402
from malice import suspicious  # noqa: E402
from provenance import (  # noqa: E402
    SESSION_COOKIE,
    cap_session,
    new_session_id,
    post_is_justified,
    session_key,
    text_fields_in_body,
    typed_string,
)
from ttl import expire, touch  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from cadence.policy import caep as caep_policy  # noqa: E402

EDGE_DIR = Path(__file__).resolve().parent
SDK_PATH = EDGE_DIR / "cadence-sdk.js"
SDK_SOURCE = SDK_PATH.read_text(encoding="utf-8")
SDK_HASHES = csp_hashes(SDK_SOURCE)


class _ModuleState:
    """Console snapshot source: this file's globals, not sys.modules.

    mitmproxy may exec the script under a name that is later dropped
    from sys.modules; looking up __name__ then KeyErrors on every poll.
    """

    def __getattr__(self, name):
        try:
            return globals()[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


_STATE = _ModuleState()

TELEMETRY_PATH = "/__cadence/telemetry"

# session_key -> list of event dicts, in arrival order. Module-level so tests
# (and a future consumer) can inspect what the proxy has buffered. The key is
# the proxy-set __cadence_sid cookie when present, the TCP peer as fallback.
# Capped per session (head dropped) by cap_session on every append.
sessions: dict[str, list[dict]] = {}

# session_key -> running SPRT log-likelihood ratio. The fusion walk's state.
score: dict[str, float] = {}

# session_key -> the walk's current terminal-or-not decision, updated at
# telemetry ingest and read at request time.
decisions: dict[str, str] = {}

# session_key -> {detector: last-counted flag}. A detector's LLR enters the
# walk once per flag CHANGE (PR 16); this is the change memory.
last_flags: dict[str, dict[str, object]] = {}

# session_key -> count of requests the proxy answered locally (401/403).
# Console display only.
blocks: dict[str, int] = {}

# session_key -> last activity unix time. Idle keys are dropped by ttl.expire.
last_seen: dict[str, float] = {}

# Recent CAEP-shaped events and console timeline (capped).
caep_log: list[dict] = []
timeline: list[dict] = []

# session_key -> reasons already emitted. One CAEP event per session and
# reason: a challenge that stays in force is one signal, not one per
# blocked retry.
caep_emitted: dict[str, set] = {}

_session_counter = itertools.count(1)
_STORES = (sessions, score, decisions, last_flags, blocks, caep_emitted)


def _client_fallback(flow) -> str:
    """Connection fallback for the session key: request host + client address."""
    try:
        host = flow.request.host
    except AttributeError:
        host = "unknown"
    try:
        addr = flow.client_conn.peername if flow.client_conn is not None else None
    except AttributeError:
        addr = None
    return f"{host}|{addr}"


def _flow_session_key(flow) -> str:
    """Cookie first, connection fallback second — same rule on request and response."""
    try:
        cookie = flow.request.headers.get("cookie")
    except AttributeError:
        cookie = None
    return session_key(cookie, _client_fallback(flow))


def _request_cookie(flow) -> str | None:
    try:
        return flow.request.headers.get("cookie")
    except AttributeError:
        return None


def _existing_sid(flow) -> str | None:
    """The sid the request already carries, or None."""
    sid = session_key(_request_cookie(flow), "")
    return sid or None


def _set_cookie_if_absent(response, flow) -> None:
    """Mint a session cookie only when the request did not already carry one.

    Rotating __cadence_sid on every HTML response was the first version's
    fatal bug: telemetry buffered under the old id, the next page minted a
    new one, and the form POST saw an empty buffer and 403'd a human.
    The cookie is minted once per browser session, here and on the telemetry
    204. Never overwrites the upstream's Set-Cookie (mitmproxy headers
    support multiple values; fakes in tests use .add when present).
    """
    if _existing_sid(flow) is not None:
        return
    sid = new_session_id(next(_session_counter))
    _add_set_cookie(response, sid)


def _add_set_cookie(response, sid: str) -> None:
    set_cookie = f"{SESSION_COOKIE}={sid}; Path=/; SameSite=Lax"
    add = getattr(response.headers, "add", None)
    if callable(add):
        add("Set-Cookie", set_cookie)
    else:
        if "Set-Cookie" not in response.headers:
            response.headers["Set-Cookie"] = set_cookie


def _note(kind: str, key: str, detail: str = "") -> None:
    timeline.append({"kind": kind, "sid": key[:16], "detail": detail})
    del timeline[:-50]


def _emit_caep(key: str, reason: str) -> None:
    emitted = caep_emitted.setdefault(key, set())
    if reason in emitted:
        return
    emitted.add(reason)
    # session-revoked is reserved for the hard 403: the session's output
    # was rejected. A 401 step-up is a challenge, not a revocation — it
    # maps to a claims change (the required assurance level moved).
    event_type = (
        caep_policy.SESSION_REVOKED
        if reason == "provenance-unjustified"
        else caep_policy.TOKEN_CLAIMS_CHANGE
    )
    evt = caep_policy.event(key, reason, event_type=event_type)
    caep_log.append(evt)
    del caep_log[:-50]
    _note("caep", key, reason)
    print(f"cadence caep: {reason} session={key[:16]}", file=sys.stderr)


class CadenceAddon:
    def request(self, flow):
        """Responsibilities in order: console, telemetry sink, step-up
        check, provenance gate, malice."""
        now = time.time()
        expire(now, last_seen, list(_STORES))
        path = flow.request.path.split("?")[0]
        if path == CONSOLE_PATH:
            self._serve_console(flow)
            return
        if path == CONSOLE_STATE_PATH:
            self._serve_console_state(flow)
            return
        if path == TELEMETRY_PATH:
            self._swallow_telemetry(flow)
            return
        if self._maybe_step_up(flow):
            key = _flow_session_key(flow)
            blocks[key] = blocks.get(key, 0) + 1
            _emit_caep(key, "step-up")
            return
        if self._enforce_provenance(flow):
            key = _flow_session_key(flow)
            blocks[key] = blocks.get(key, 0) + 1
            _emit_caep(key, "provenance-unjustified")
            return
        self._note_malice(flow)

    def _serve_console(self, flow):
        """Serve the demo console page. Proxy-owned path, never forwarded."""
        from mitmproxy import http

        page = replace_state_path(PAGE, CONSOLE_STATE_PATH)
        flow.response = http.Response.make(
            200,
            page.encode("utf-8"),
            {
                "Content-Type": "text/html; charset=utf-8",
                "Cache-Control": "no-store",
            },
        )

    def _serve_console_state(self, flow):
        """State snapshot as JSON, same ownership rule as telemetry."""
        from mitmproxy import http

        payload = snapshot(_STATE).encode("utf-8")
        flow.response = http.Response.make(
            200,
            payload,
            {
                "Content-Type": "application/json",
                "Cache-Control": "no-store",
            },
        )

    def _accumulate(self, key: str, events: list[dict]) -> None:
        """Fold detector verdicts into the SPRT walk — each verdict ONCE.

        A detector's LLR contribution is counted only when its flag CHANGES
        (None -> True, True -> False, ...). Re-evaluating every flush while
        the flag stays true double-counts the same session evidence: a
        machine-like buffer that stays machine-like through ten beacons
        would add automation's LLR ten times, and the walk would cross the
        step-up bound on volume of identical evidence, not weight of new
        evidence. The per-session last-seen flags live in `last_flags`.

        Once the walk has said step-up, only a terminal 'clean' decision
        clears it: an intermediate 'continue' after more evidence must not
        lift the challenge, because the evidence that crossed the bound is
        still in the sum.
        """
        signals = {
            "automation": is_automated(events),
            "drift": (drift_signal(events) or {}).get("drift"),
            "provenance": None,  # per-request, evaluated in the gate below
        }
        seen = last_flags.setdefault(key, {})
        fresh = {}
        for name, fired in signals.items():
            if name not in seen or seen[name] != fired:
                fresh[name] = fired
                seen[name] = fired
            # Unchanged (or None-before-None) flags contribute nothing:
            # the walk already holds this evidence once.
        # fusion_update, not `update`: mitmproxy registers this script
        # module as an addon, and update(flows) is a hook name.
        state = fusion_update(score.get(key, 0.0), fresh)
        score[key] = state["llr"]
        if decisions.get(key) == "step-up":
            if state["decision"] != "clean":
                decisions[key] = "step-up"  # sticky: only clean clears
        else:
            decisions[key] = state["decision"]

    def _flag(self, key: str, name: str, fired) -> None:
        """Count one detector outcome if it changed, same rule as _accumulate."""
        seen = last_flags.setdefault(key, {})
        if name in seen and seen[name] == fired:
            return
        seen[name] = fired
        state = fusion_update(score.get(key, 0.0), {name: fired})
        score[key] = state["llr"]
        if decisions.get(key) == "step-up":
            if state["decision"] != "clean":
                decisions[key] = "step-up"
        else:
            decisions[key] = state["decision"]

    def _note_malice(self, flow) -> None:
        """Lexical URL+body triage into the walk. Does not 403 by itself."""
        try:
            url = flow.request.path
        except AttributeError:
            url = ""
        body = getattr(flow.request, "raw_content", None) or b""
        hit = suspicious(url, body)
        key = _flow_session_key(flow)
        touch(last_seen, key, time.time())
        if hit:
            self._flag(key, "malice", True)
            _note("malice", key, hit)

    def _maybe_step_up(self, flow) -> bool:
        """401 + WWW-Authenticate (RFC 9470) when the fusion score says so.

        The walk's evidence accumulates at telemetry ingest (_accumulate);
        this check only READS the current decision. A 'step-up' decision is
        answered locally with 401 and a challenge — never forwarded — and
        stays in force for the session: evidence does not vanish, so only
        a 'clean' decision (strong sustained honest evidence) clears it.
        """
        if decisions.get(_flow_session_key(flow)) != "step-up":
            return False
        from mitmproxy import http

        # RFC 9470 (OAuth 2.0 Step Up Authentication Challenge Protocol):
        # a Bearer challenge with error=insufficient_user_authentication
        # and acr_values naming the assurance level required.
        flow.response = http.Response.make(
            401,
            b"cadence: step-up authentication required for this session.\n",
            {
                "Content-Type": "text/plain",
                "WWW-Authenticate": (
                    'Bearer error="insufficient_user_authentication", '
                    'error_description="behavioral score exceeded the step-up bound", '
                    'acr_values="cadence-behavioral-verified"'
                ),
            },
        )
        return True

    def _swallow_telemetry(self, flow):
        """Buffer telemetry under the session key; never forward it upstream.

        Any method hitting the exact path is swallowed, not just POST — the
        path belongs to the proxy, so nothing on it should ever reach the
        upstream server regardless of verb.
        """
        events: list[dict] = []
        if flow.request.raw_content:
            try:
                payload = json.loads(flow.request.raw_content)
                maybe = payload.get("events") or []
                # list(1) raises TypeError, and that would error the flow
                # before the 204 below — turning a garbage payload into a
                # proxy-visible error instead of a swallow.
                if isinstance(maybe, list):
                    events = maybe
            except (ValueError, AttributeError):
                events = []
        # Mint BEFORE buffering: if this beacon has no cookie yet (it can
        # beat the first HTML response), the buffer and the newly issued
        # cookie must share one id, or one browser becomes two sessions.
        existing = _existing_sid(flow)
        key = existing if existing is not None else new_session_id(next(_session_counter))
        # Detectors run HERE, once per round, on the freshly extended
        # buffer — the only moment new evidence exists. Running them per
        # page request instead re-evaluates the whole buffer every time and
        # lets earlier evidence evaporate when the buffer's character
        # changes (a second driver dilutes whole-stream automation below
        # its threshold, silently un-firing a signal the walk already
        # counted). SPRT requires evidence to accumulate monotonically.
        # Empty beacons are NOT activity: an events-free heartbeat must not
        # touch last_seen, or the SDK's idle-tab interval keeps a stolen
        # sid's buffer alive past the TTL forever.
        if events:
            buffered = sessions.setdefault(key, [])
            buffered.extend(events)
            sessions[key] = cap_session(buffered)
            touch(last_seen, key, time.time())
            self._accumulate(key, sessions[key])
            # Recapture dump must never break the telemetry ack: a bad
            # CADENCE_DUMP_DIR (file path, perms, full disk) fails open.
            try:
                append_flush(key, events)
            except OSError:
                pass
        # A response set in the request hook short-circuits the proxy:
        # mitmproxy answers locally and nothing is forwarded upstream.
        from mitmproxy import http

        flow.response = http.Response.make(
            204,
            b"",
            {"Content-Type": "text/plain"},
        )
        if existing is None:
            _add_set_cookie(flow.response, key)

    def _enforce_provenance(self, flow):
        """403 a text-bearing form POST from a session that typed nothing.

        The block is local: the request never reaches the upstream server.
        Fail-open by construction for anything the rules do not classify as
        text (JSON, multipart, unmatched field names, passwords).
        """
        if (flow.request.method or "").upper() != "POST":
            return False
        body = flow.request.raw_content or b""
        content_type = flow.request.headers.get("content-type", "")
        events = sessions.get(_flow_session_key(flow), [])
        if post_is_justified(body, content_type, events):
            return False
        print(
            "cadence 403 provenance: "
            f"typed={typed_string(events)!r} "
            f"fields={text_fields_in_body(body, content_type)!r} "
            f"n={len(events)}",
            file=sys.stderr,
        )
        from mitmproxy import http

        flow.response = http.Response.make(
            403,
            b"cadence: form submission without recorded keystrokes for this session.\n",
            {"Content-Type": "text/plain"},
        )
        return True

    def response(self, flow):
        response = flow.response
        if response is None:
            return
        # Proxy-owned paths are answered locally and must NOT get the SDK
        # injected or a session cookie minted: the console is not a subject
        # of the measurement, and minting there splits one browser into
        # two sessions.
        try:
            req_path = flow.request.path.split("?")[0]
        except AttributeError:
            req_path = ""
        if req_path.startswith("/__cadence"):
            return
        if not is_html(response.headers.get("content-type", "")):
            return
        body = response.content or b""
        new = inject(body, SDK_SOURCE)
        if new != body:
            response.content = new
            if "Content-Length" in response.headers:
                del response.headers["Content-Length"]
            self._allow_injected_scripts_in_csp(response)
        # Mint the session cookie only on first sight: telemetry and POSTs
        # from this browser then share one key even across keep-alive
        # reconnects or HTTP/2 stream splits. Never rotates an existing sid.
        _set_cookie_if_absent(response, flow)

    def _allow_injected_scripts_in_csp(self, response) -> None:
        """Append our script hashes to script-src so a strict CSP lets the
        injected SDK run. Without this, a page with Content-Security-Policy
        blocks the inline scripts, telemetry never starts, and provenance
        is blind. No CSP header → nothing to extend.

        Only script-src (or a default-src fallback) is touched, and only by
        appending tokens — never removing the page's own restrictions.
        """
        csp = response.headers.get("Content-Security-Policy")
        if not csp:
            return
        import re

        directives = re.split(r"\s*;\s*", csp)
        target = None
        for i, d in enumerate(directives):
            name = d.split(None, 1)[0].lower() if d.strip() else ""
            if name == "script-src":
                target = i
                break
            if name == "default-src" and target is None:
                target = i
        if target is None:
            # A policy with neither script-src nor default-src cannot govern
            # scripts; nothing to extend.
            return
        # CSP2+ deactivates 'unsafe-inline' on a directive the moment any
        # hash or nonce appears in it. If the governing directive already
        # allows inline scripts, appending our hashes would BREAK the page's
        # own inline scripts while adding nothing: they already permit ours.
        if "'unsafe-inline'" in directives[target]:
            return
        existing = directives[target]
        additions = [h for h in SDK_HASHES if h not in existing]
        if not additions:
            return
        directives[target] = existing.rstrip() + " " + " ".join(additions)
        response.headers["Content-Security-Policy"] = "; ".join(directives)


addons = [CadenceAddon()]
