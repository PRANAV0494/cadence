"""Live console: a demo page over WebSocket showing proxy state.

Served by the addon itself at /__cadence/console — the proxy owns the
path, nothing is forwarded. The page opens a WebSocket to
/__cadence/console/ws; on each message it renders session id, last SPRT
decision, per-detector flags, and any 401/403 the proxy has issued.

Demo only: no detector logic lives here and none is added.
"""

from __future__ import annotations

import json

CONSOLE_PATH = "/__cadence/console"
CONSOLE_WS_PATH = "/__cadence/console/ws"

PAGE = """<!doctype html>
<html>
<head><meta charset="utf-8"><title>cadence console</title>
<style>
  body { font-family: ui-monospace, monospace; background: #0b0f0c; color: #9fe870; margin: 2rem; }
  h1 { font-size: 1.1rem; border-bottom: 1px solid #29402f; padding-bottom: .4rem; }
  table { border-collapse: collapse; margin-top: 1rem; }
  td, th { border: 1px solid #29402f; padding: .35rem .8rem; text-align: left; font-size: .9rem; }
  .step-up { color: #ff6b6b; } .clean { color: #9fe870; } .continue { color: #e8c970; }
  #conn { font-size: .8rem; color: #6b8f72; }
</style></head>
<body>
<h1>cadence console (demo)</h1>
<div id="conn">connecting...</div>
<table><thead>
<tr><th>session</th><th>decision</th><th>score</th><th>automation</th><th>drift</th><th>provenance</th><th>blocks</th></tr>
</thead><tbody id="rows"></tbody></table>
<script>
function cell(text, cls) {
  var td = document.createElement("td");
  td.textContent = text == null ? "-" : String(text);
  if (cls) td.className = cls;
  return td;
}
function render(state) {
  var rows = document.getElementById("rows");
  rows.innerHTML = "";
  (state.sessions || []).forEach(function (s) {
    var tr = document.createElement("tr");
    tr.appendChild(cell(s.sid));
    tr.appendChild(cell(s.decision, s.decision));
    tr.appendChild(cell(s.score == null ? null : s.score.toFixed(2)));
    tr.appendChild(cell(s.flags && s.flags.automation));
    tr.appendChild(cell(s.flags && s.flags.drift));
    tr.appendChild(cell(s.flags && s.flags.provenance));
    tr.appendChild(cell(s.blocks));
    rows.appendChild(tr);
  });
  document.getElementById("conn").textContent =
    state.dropped + " blocked request(s) — live";
}
function connect() {
  var ws = new WebSocket(
    (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "%WS_PATH%"
  );
  ws.onmessage = function (m) { render(JSON.parse(m.data)); };
  ws.onclose = function () {
    document.getElementById("conn").textContent = "reconnecting...";
    setTimeout(connect, 1500);
  };
}
connect();
</script>
</body></html>"""


def replace_ws_path(page: str, ws_path: str) -> str:
    return page.replace("%WS_PATH%", ws_path)


def snapshot(state) -> str:
    """JSON for one console push, from the addon's module-level state.

    `state` is the addon module: sessions/decisions/score/last_flags dicts
    plus a `blocks` counter per session maintained by the gate hooks.
    """
    sids = set(state.sessions) | set(state.decisions) | set(state.score)
    payload = {
        "sessions": [
            {
                "sid": sid if len(sid) < 24 else sid[:8] + "..." + sid[-6:],
                "decision": state.decisions.get(sid),
                "score": state.score.get(sid),
                "flags": state.last_flags.get(sid, {}),
                "blocks": state.blocks.get(sid, 0),
            }
            for sid in sorted(sids)
        ],
        "dropped": sum(state.blocks.values()),
    }
    return json.dumps(payload)
