# Unported test suites

These came from the pre-consolidation repositories and **do not run**. They are
excluded from the default pytest run via `norecursedirs` in `pyproject.toml`,
and CI does not gate on them.

| File | Why it fails | From |
|---|---|---|
| `test_integration.py` | `from bot.api import BotAPI` → `ModuleNotFoundError: No module named 'bot'`. The `bot/` package was not carried over; only `model_manager.py` and `risk_engine.py` came across, into `reference/`. | `KEYSTROKE_models/tests/` |
| `test_keystroke_dynamics.py` | All 7 tests fail on `ModuleNotFoundError`. Depends on `src/keystroke/` (authenticator, feature extractor, session manager), which was not copied — its role is taken by `cadence/features/keystroke.py`. | `KEYSTROKE_models/tests/` |

They are kept because they encode assumptions worth porting: the integration
test exercises a full inference path end to end, and the keystroke test covers
authenticator load, user identification, and anomaly thresholds — all behaviour
the new detectors will need equivalents for.

**Do not fix these by adding the old packages back.** Port the intent into new
tests against the current layout, then delete the file here.
