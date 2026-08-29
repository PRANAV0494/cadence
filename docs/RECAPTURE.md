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
  not committed to git.
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
cd "C:\Users\prana\OneDrive\Desktop\COLLEGE PROJECTS\CADENCE"
& ".\.venv\Scripts\Activate.ps1"
New-Item -ItemType Directory -Force -Path ".\data\private\recapture" | Out-Null
$env:CADENCE_DUMP_DIR = (Resolve-Path ".\data\private\recapture").Path
.\.venv\Scripts\cadence.exe demo --port 9000
```

Leave that window running. Participant:

1. Open http://127.0.0.1:9000/
2. Type a normal English sentence (not a paste, not a password).
3. Click **submit** (do not press Enter in the box).
4. Green "allowed" is a good take. 403 means keystrokes did not reach
   the proxy — discard that file and retake.

Then in another PowerShell, **before the next person**:

```powershell
Get-ChildItem .\data\private\recapture | Sort-Object LastWriteTime
```

Rename the newest file to a **pseudonym**, not a real name:

```powershell
Rename-Item .\data\private\recapture\<sid>.jsonl p01.jsonl
```

Keep the name map off this repo (notebook, paper notes, not git).

Close the form tab (or restart the demo) so the next person is a new
`__cadence_sid`. Target: 10–20 people, one or two sentences each.

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
