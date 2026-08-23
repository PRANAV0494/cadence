"""
Tests for the repository guards.

These could not exist while the guards were heredocs inside ci.yml, and their
absence cost a red CI run: a local check that retyped the scanner into a scratch
script passed, while the workflow shipped an unnarrowed pattern that flagged
`_required("JWT_SECRET_KEY")` as a hardcoded secret.

The decision under test is that a hit is judged on the **value**, not the line.
Skipping a whole line because it contained the word "example" or an HTML tag
meant a real key sharing that line was invisible.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_deploy_template import parameters_with_defaults  # noqa: E402
from check_secrets import scan_line, scan_repo  # noqa: E402


# ── real secrets, in every format the old regex missed ─────────

@pytest.mark.parametrize(
    "line",
    [
        'SECRET_KEY = "hunter2hunter2"',                  # double-quoted
        "PASSWORD = 'singlequoted123'",                   # single-quoted
        "JWT_SECRET_KEY=unquotedsecretvalue",             # unquoted .env style
        'JwtSecretKey: "prod-signing-key-xyz"',           # YAML
        'API_KEY = "sk-abcdefghijklmnop"',                # provider key
        "aws_access_key_id = AKIAZZ7Q3XKL2MNPQRST",       # AWS
        "-----BEGIN RSA PRIVATE KEY-----",                # PEM
        'ADMIN_PASSWORD_HASH = "$2b$12$abcdefghijklmno"',  # bcrypt hash
    ],
)
def test_real_secrets_are_caught(line):
    assert scan_line(line) is True


def test_a_real_key_is_not_hidden_by_the_word_example():
    """
    BENIGN used to be applied to the whole line, so any line mentioning
    'example' was skipped entirely — including one that also held a live key.
    """
    assert scan_line('JWT_SECRET_KEY = "supersecretvalue123"  # example') is True


def test_a_real_key_is_not_hidden_by_an_html_tag():
    """
    Same hole via the `<[^>]+>` alternative in the old line-wide skip: any
    markup on the line exempted it. The assignment has to carry a
    secret-shaped *name* for this to be a hit at all — in
    `<input name="password" value="...">` the assigned name is `value`,
    which is not one, so that line is correctly ignored.
    """
    assert scan_line('<div>API_KEY = "sk-liveproductionkey"</div>') is True
    assert scan_line('<input name="password" value="supersecretvalue123">') is False


# ── things that are not secrets ────────────────────────────────

@pytest.mark.parametrize(
    "line",
    [
        'SECRET_KEY = _required("JWT_SECRET_KEY")',        # a call
        'ADMIN_PASSWORD_HASH = os.environ["ADMIN_PASSWORD_HASH"]',  # a subscript
        "JwtSecretKey: !Ref JwtSecretKey",                 # CFN reference
        'JWT_SECRET_KEY = "${JWT_SECRET_KEY}"',            # interpolation
        'API_TOKEN = "<your-token-here>"',                 # placeholder
        'PASSWORD = "changeme-please"',                    # placeholder
        'SECRET = "xxxxxxxxxx"',                           # placeholder
        "JWT_SECRET_KEY=",                                 # empty, as .env.example ships
        "# Set JWT_SECRET_KEY before starting the API",    # prose
    ],
)
def test_non_secrets_are_ignored(line):
    assert scan_line(line) is False


def test_placeholder_is_judged_on_the_value_not_the_line():
    """
    'example' inside the value marks a placeholder; 'example' elsewhere on the
    line must not excuse a real value.
    """
    assert scan_line('API_KEY = "example-key-value"') is False
    assert scan_line('API_KEY = "sk-liveproductionkey"  # see example above') is True


# ── the repository itself ──────────────────────────────────────

def test_repository_is_clean():
    assert scan_repo() == []


def test_scanner_does_not_flag_its_own_patterns():
    """The scanner is skipped by path; without that it matches its own regexes."""
    assert not any("check_secrets" in h for h in scan_repo())


def test_self_exemptions_are_exact_paths_not_directories():
    """
    Only two files may hold secret-shaped strings: the scanner and this file.
    A directory-level exemption would silently cover future files -- the same
    mistake the models/network/ blob allowlist made.
    """
    from check_secrets import SKIP_EXACT, SKIP_PREFIXES

    assert SKIP_EXACT == {
        ".env.example",
        "scripts/check_secrets.py",
        "tests/test_repo_guards.py",
    }
    assert not any(p.startswith(("scripts/", "tests/")) for p in SKIP_PREFIXES)


def test_a_secret_in_another_test_file_would_still_be_caught():
    """The exemption is this file only, not tests/ generally."""
    assert scan_repo(["tests/test_api_submit.py"]) == []
    assert scan_line('SECRET_KEY = "realkeyinanothertest"') is True


# ── deploy template guard ──────────────────────────────────────

def test_default_on_a_secret_parameter_is_caught():
    text = (
        "Parameters:\n"
        "  JwtSecretKey:\n"
        "    Type: String\n"
        "    Default: some-hardcoded-production-key\n"
        "  AdminUsername:\n"
        "    Type: String\n"
    )
    assert parameters_with_defaults(text) == ["JwtSecretKey"]


def test_any_default_counts_not_just_known_literals():
    """
    The old guard grepped for 'change-me' and '$2b$' — the two values already
    removed. A fresh hardcoded key would have passed.
    """
    text = "Parameters:\n  AdminPasswordHash:\n    Type: String\n    Default: brand-new-value\n"
    assert parameters_with_defaults(text) == ["AdminPasswordHash"]


def test_template_without_defaults_passes():
    text = (
        "Parameters:\n"
        "  JwtSecretKey:\n"
        "    Type: String\n"
        "    NoEcho: true\n"
        "  AdminUsername:\n"
        "    Type: String\n"
    )
    assert parameters_with_defaults(text) == []


def test_the_real_template_has_no_secret_defaults():
    template = Path(__file__).resolve().parents[1] / "deploy" / "template.yaml"
    assert parameters_with_defaults(template.read_text(encoding="utf-8")) == []
