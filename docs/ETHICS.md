# Ethics

CADENCE records **keystroke timing**, not passwords (password fields are
not gated) and not the pasted *content* (paste events store length only).

1. **Consent.** Any capture from real people needs informed consent: what is
   collected, how long it is kept, how to withdraw. Timing is behavioural
   biometric data.
2. **The proxy injects a script** into pages that pass through it. Use it
   only on systems you own or have written authorisation to test.
3. **Do not claim unspoofability.** The SDK is in the driver's DOM.
4. Participant exports under `data/private/` stay out of git.

See CONTRIBUTING.md for data-handling rules.
