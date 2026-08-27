# Limitations

- Research prototype. Not a CAPTCHA, not an authenticator, not production.
- SDK can be patched or suppressed; empty telemetry on a text POST is itself
  a detection, but forged *consistent* telemetry is an arms race on timing.
- Keystroke dynamics is a weak factor (Van Hamme et al., EuroS&P 2023).
  CADENCE uses it as a risk signal that can trigger step-up.
- Browser timer clamping degrades resolution vs lab datasets.
- Session TTL is 30 minutes of idle; a stolen cookie used sooner still
  carries whatever keystrokes were already buffered.
- Malice is lexical. `Accept: */*` is not scanned (headers out of scope).
- Network CICIDS / flowtap is not in the live path (wrong-domain models
  were dropped; see MANIFEST.md).
