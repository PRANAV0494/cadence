"""
The API refuses to start without configuration — including when a variable is
set but empty.

`JWT_SECRET_KEY=` is *set*, so trapping only KeyError let import succeed and
every admin token was signed with an empty key. `.env.example` shipped exactly
that line, so following the documented setup produced the insecure state.
"""

import importlib
import sys

import pytest


def _reload_auth(monkeypatch, **env):
    for k in ("JWT_SECRET_KEY", "ADMIN_USERNAME", "ADMIN_PASSWORD_HASH"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("cadence.api.auth", None)
    return importlib.import_module("cadence.api.auth")


COMPLETE = {
    "JWT_SECRET_KEY": "a-real-looking-key",
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD_HASH": "$2b$12$" + "K" * 53,
}


def test_complete_config_imports(monkeypatch):
    mod = _reload_auth(monkeypatch, **COMPLETE)
    assert mod.SECRET_KEY == "a-real-looking-key"


@pytest.mark.parametrize(
    "blank",
    ["", "   ", "\t", "\n"],
    ids=["empty", "spaces", "tab", "newline"],
)
def test_empty_secret_is_treated_as_missing(monkeypatch, blank):
    env = {**COMPLETE, "JWT_SECRET_KEY": blank}
    with pytest.raises(RuntimeError, match="not set, or is empty"):
        _reload_auth(monkeypatch, **env)


def test_missing_variable_still_fails(monkeypatch):
    env = {k: v for k, v in COMPLETE.items() if k != "ADMIN_USERNAME"}
    with pytest.raises(RuntimeError, match="ADMIN_USERNAME"):
        _reload_auth(monkeypatch, **env)


def test_error_says_nothing_reads_dotenv_automatically(monkeypatch):
    """
    The old message told operators to copy .env.example to .env, but nothing
    loads .env — no python-dotenv, no load_dotenv call.
    """
    env = {**COMPLETE, "JWT_SECRET_KEY": ""}
    with pytest.raises(RuntimeError) as exc:
        _reload_auth(monkeypatch, **env)
    assert "--env-file" in str(exc.value)
