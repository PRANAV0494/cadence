# Ethics

CADENCE's capture SDK listens on the whole document and sends per-key
`key`/`code` values with timestamps to the proxy — **including characters
typed into password fields**. Pasted *content* is never sent (paste
events store length only). Password *form fields* are excluded from the
provenance 403 gate, but that is a detection fail-open, not a capture
exclusion: do not describe this as "not recording passwords".

1. **Consent.** Any capture from real people needs informed consent: what is
   collected, how long it is kept, how to withdraw. Timing is behavioural
   biometric data.
2. **The proxy injects a script** into pages that pass through it. Use it
   only on systems you own or have written authorisation to test.
3. **Do not claim unspoofability.** The SDK is in the driver's DOM.
4. Participant exports under `data/private/` stay out of git.

See CONTRIBUTING.md for data-handling rules.
