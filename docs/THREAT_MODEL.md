# Threat model

The adversary is **already past login**: same session cookie, device, IP, and
browser fingerprint. MFA and CAPTCHA have already fired and gone quiet.

CADENCE asks three questions on that live session:

1. **Provenance** — was submitted text produced by observed keystrokes?
2. **Automation** — does timing look synthesised?
3. **Drift** — did the driver change since the start of this session?

A fourth, lexical **malice** signal (`edge/malice.py`, URL and body only)
feeds the same SPRT walk under deliberately weak placeholder rates: one
hit cannot cross the step-up bound by itself. It is triage, not a WAF —
the matching request is still forwarded.

**In scope:** form POSTs (and JSON/multipart text fields) through the proxy;
keystroke telemetry the proxy itself received.

**Out of scope:** stopping malware, replacing passwords, detecting every AI
agent, and traffic that never hits this proxy.

The capture SDK runs in the adversary's DOM and can be patched. Server-side
reconciliation raises the cost of a silent fill; it does not close the door.
An agent that types character-by-character with realistic delays reconciles
and must be caught by timing or drift.

This is a research prototype. It is not production software.
