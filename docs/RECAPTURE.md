# Human recapture

The current SDK (`edge/cadence-sdk.js`) pairs presses by `event.code` + a
monotonic `seq`, not caret index. The old export under `data/private/` was
captured with the buggy matcher and is **not** a dwell dataset: 85% of
human mean dwells there are negative.

This note is the lab procedure to capture **new** sessions. It is not a
field result. Do not quote TPR/FPR/EER from it until `check_dwell`
passes and you have written up consent.

See `docs/ETHICS.md` and `CONTRIBUTING.md`. Timing is behavioural
biometric data. The SDK sends per-key `key`/`code` from the whole
document, including password fields — use only the demo `message` box.

## Consent (read before anyone types)

Tell the participant, in substance:

- You are recording **keystroke timings and the characters you type** in
  this demo box, for a student research prototype.
- Files stay on the experimenter's machine under `data/private/` and are
  not committed to git. That location plus full-disk encryption is the
  actual protection — the per-file permission the dump sets is best-effort
  and does nothing on Windows, so do not promise more than the machine
  itself provides.
- You can stop at any time; say so and we delete your file.
- Do not type a real password or other secrets.

If they do not agree, do not start the demo for them.

## What you save

One JSONL file per browser session, gitignored:

`data/private/recapture/<session>.jsonl`

Each line is one telemetry flush: `{"events": [ ... SDK events ... ]}`.
That is the same shape `cadence eval` already consumes.

Never `git add data/private/`.

## Capture

Auto-forward off in VS Code (`Remote: Auto Forward Ports`).

```powershell
cd <repo-root>  # the CADENCE checkout, e.g. .\CADENCE on Windows
& ".\.venv\Scripts\Activate.ps1"  # Windows; on macOS/Linux: source .venv/bin/activate
New-Item -ItemType Directory -Force -Path ".\data\private\recapture" | Out-Null
$env:CADENCE_DUMP_DIR = (Resolve-Path ".\data\private\recapture").Path
.\.venv\Scripts\cadence.exe demo --port 9000
```

Leave that window running. Participant:

1. Open http://127.0.0.1:9000/
2. Type a normal English sentence (not a paste, not a password).
3. Click **submit** (do not press Enter in the box).
4. Green "allowed" is a good take. 403 means keystrokes did not reach the
   proxy — see *Retakes* below; the file is appended to, so a retake does
   **not** replace the bad take on its own.

Then in another PowerShell, **before the next person**:

```powershell
Get-ChildItem .\data\private\recapture | Sort-Object LastWriteTime
```

Rename the newest file to a **pseudonym**, not a real name:

```powershell
Rename-Item .\data\private\recapture\<sid>.jsonl p01.jsonl
```

Keep the name map off this repo (notebook, paper notes, not git).

### Reset the session between participants — this step is load-bearing

Closing the tab is **not** enough, and neither is restarting the demo:

- `__cadence_sid` is set with no `Max-Age`/`Expires`, so it is a browser-session
  cookie. It survives tab close and outlives `cadence demo`; only a full browser
  **quit** clears it.
- The proxy mints a sid only when the request does not already carry one, so
  restarting `mitmdump` changes nothing — the browser keeps sending the old
  cookie.
- `cadence demo` uses your normal browser and launches no profile of its own,
  so there is nothing that resets itself.

Skip this and participants 2..N append to the **same** `<sid>.jsonl`. The
rename step then labels one file `p01` while it holds two people, and the dwell
gate passes the mixture without complaint.

Do one of these before each new participant:

- **Delete the cookie** — DevTools (F12) → Application → Cookies →
  `http://127.0.0.1:9000` → delete `__cadence_sid`. Fastest.
- **Quit the browser entirely** — every window, not just the tab.

Then confirm it worked: the next submit must create a **new** file in the dump
directory. If the newest file's timestamp moved instead of a new one appearing,
the sid did not rotate — stop and clear the cookie before continuing.

### Retakes

A 403, a paste, a wrong-language sentence: the events are already in that sid's
file, because the dump appends. To redo a take, reset the session as above
**and** delete the partial file, then have them type again.

Target: 10–20 people, one or two sentences each.

## Dwell gate (run before you call it a dataset)

```powershell
.\.venv\Scripts\python.exe evaluation\check_dwell.py .\data\private\recapture\p01.jsonl
```

Pass means: at least 10 paired character presses, **median dwell > 0**,
and fewer than 5% of pairs negative. Fail means stop — do not train, do
not quote automation rates. The rewritten SDK should pass; if it does
not, capture is still wrong.

All files:

```powershell
Get-ChildItem .\data\private\recapture\*.jsonl | ForEach-Object {
  Write-Output $_.Name
  .\.venv\Scripts\python.exe evaluation\check_dwell.py $_.FullName
}
```

## Replay (after dwell passes)

```powershell
.\.venv\Scripts\cadence.exe eval .\data\private\recapture\p01.jsonl
```

That prints the SPRT walk on **this** session. It is not leave-one-agent-out
and not a field TPR.

## Out of scope here

- Agent-framework captures and leave-one-agent-out
- Adversarial humanization
- Putting numbers from `check_dwell` or `cadence eval` into the README
  without a `results.json` source
