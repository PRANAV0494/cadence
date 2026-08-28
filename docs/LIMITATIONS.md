# Limitations

- Research prototype. Not a CAPTCHA, not an authenticator, not production.
- SDK can be patched or suppressed; empty telemetry on a text POST is itself
  a detection, but forged *consistent* telemetry is an arms race on timing.
- Keystroke dynamics is a weak factor (Van Hamme et al., EuroS&P 2023).
  CADENCE uses it as a risk signal that can trigger step-up.
- Browser timer clamping degrades resolution vs lab datasets.
- Session idle expiry is `TTL_SECONDS` in `edge/ttl.py` (30 minutes of
  idle); a stolen `__cadence_sid` used sooner still reuses whatever
  keystrokes were already buffered. Only event-bearing telemetry counts
  as activity — empty heartbeats do not keep a session alive.
- The lexical malice signal (`edge/malice.py`) scans URL and body only —
  headers like `Accept: */*` are out of its scope — and runs on
  placeholder rates: it contributes to the walk but cannot 401 alone,
  and the matching request is still forwarded.
- Network CICIDS / flowtap is not in the live path. The copied
  `models/network/cicids2017_*` artifact sits unused in the tree:
  fabricated HTTP→CICIDS feature vectors were rejected and the flowtap
  sidecar was never built (see MANIFEST.md).
