"""
HTTP malice detector tests. Canonical public payloads only — no fabricated
CICIDS vectors. Headers are out of scope, pinned by the Accept: */* test.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"

sys.path.insert(0, str(EDGE))

from malice import suspicious  # noqa: E402


# ── canonical payloads fire ────────────────────────────────────

def test_sqli_union_select():
    assert suspicious("/search?q=1' UNION SELECT * FROM users--") == "sqli"


def test_sqli_or_tautology():
    assert suspicious("/login?u=admin' OR '1'='1") == "sqli"


def test_sqli_sleep():
    assert suspicious("/item?id=1 AND SLEEP(5)") == "sqli"


def test_xss_script_tag():
    assert suspicious("/comment?text=<script>alert(1)</script>") == "xss"


def test_xss_onerror():
    assert suspicious("/comment?text=<img src=x onerror=alert(1)>") == "xss"


def test_traversal_etc_passwd():
    assert suspicious("/download?f=../../etc/passwd") == "traversal"


def test_body_is_checked_too():
    body = b"message=hello'; DROP TABLE users; --"
    assert suspicious("/post", body) is not None


# ── ordinary traffic must not fire ─────────────────────────────

def test_plain_urls_pass():
    assert suspicious("/search?q=keystroke+dynamics+research") is None
    assert suspicious("/api/users/123/posts?page=2&sort=recent") is None
    assert suspicious("/") is None


def test_benign_body_words_do_not_fire():
    """Words that appear in attack payloads but in benign sentences."""
    assert suspicious("/chat", b"message=we select the union representative") is None


def test_headers_are_out_of_scope():
    """The detector takes URL and body only. Accept: */* is a browser
    default, not an attacker signature — it must never reach the patterns,
    and the function signature has no header parameter at all."""
    import inspect

    params = list(inspect.signature(suspicious).parameters)
    assert params == ["url", "body"]
    # A wildcard-accept request with a clean URL/body is clean.
    assert suspicious("/api/items?limit=10", b"") is None


def test_empty_inputs():
    assert suspicious("") is None
    assert suspicious(None, None) is None


def test_binary_body_does_not_crash():
    assert suspicious("/upload", bytes(range(256))) is not None or True
    # Whatever it returns, it must not raise; binary junk may or may not
    # match the lexical patterns — both outcomes are acceptable here.
