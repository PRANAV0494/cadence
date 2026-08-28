# Limitations

- Research prototype. Not a CAPTCHA, not an authenticator, not production.
- SDK can be patched or suppressed; empty telemetry on a text POST is itself
  a detection, but forged *consistent* telemetry is an arms race on timing.
- Keystroke dynamics is a weak factor (Van Hamme et al., EuroS&P 2023).
  CADENCE uses it as a risk signal that can trigger step-up.
- Browser timer clamping degrades resolution vs lab datasets.
- Sessions have **no idle expiry** here: buffers live for the proxy
  process lifetime, so a stolen `__cadence_sid` reuses whatever
  keystrokes were already buffered until the process dies. An idle TTL
  is on a sibling branch, not on this one.
- The lexical malice module (`edge/malice.py`) scans URL and body only —
  headers like `Accept: */*` are out of its scope — and it is **not
  invoked on the live request path** on this branch.
- Network CICIDS / flowtap is not in the live path. The copied
  `models/network/cicids2017_*` artifact sits unused in the tree:
  fabricated HTTP→CICIDS feature vectors were rejected and the flowtap
  sidecar was never built (see MANIFEST.md).
