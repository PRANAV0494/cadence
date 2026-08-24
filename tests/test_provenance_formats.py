"""
JSON / multipart provenance tests: the same substring rule as urlencoded,
for JSON string fields and multipart text parts. Files and binaries fail
open by design.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EDGE = REPO / "edge"

sys.path.insert(0, str(EDGE))

from provenance import post_is_justified, text_fields_in_body  # noqa: E402

CRLF = chr(13) + chr(10)
JSON = "application/json"
MULTI = "multipart/form-data; boundary=B"

FORM = "application/x-www-form-urlencoded"


def _k(key: str) -> dict:
    return {"event_type": "keydown", "is_modifier": False, "is_paste": False, "key": key}


def _typed(text: str) -> list[dict]:
    return [_k(c) for c in text]


def _multipart(*parts: tuple) -> bytes:
    """parts: (name, value, extra_headers) tuples."""
    out = []
    for name, value, extra in parts:
        head = f'Content-Disposition: form-data; name="{name}"'
        if extra:
            head += CRLF + extra
        out.append("--B" + CRLF + head + CRLF + CRLF + value + CRLF)
    return ("".join(out) + "--B--").encode()


# ── JSON ───────────────────────────────────────────────────────

def test_json_text_field_is_extracted():
    assert text_fields_in_body(b'{"message": "hello world"}', JSON) == {
        "message": "hello world"
    }


def test_json_non_string_and_non_text_fields_are_ignored():
    assert text_fields_in_body(b'{"message": 123}', JSON) == {}
    assert text_fields_in_body(b'{"other": "text"}', JSON) == {}
    assert text_fields_in_body(b'[1, 2]', JSON) == {}
    assert text_fields_in_body(b'not json', JSON) == {}


def test_json_uses_the_substring_rule():
    assert post_is_justified(b'{"message": "hello"}', JSON, _typed("hello")) is True
    assert post_is_justified(b'{"message": "hello"}', JSON, _typed("h")) is False
    assert post_is_justified(b'{"message": "hello"}', JSON, []) is False


# ── multipart ──────────────────────────────────────────────────

def test_multipart_text_part_is_extracted():
    body = _multipart(("message", "hello world", None))
    assert text_fields_in_body(body, MULTI) == {"message": "hello world"}


def test_multipart_file_part_fails_open():
    """filename= marks a file: never checked, whatever its content-type."""
    body = _multipart(
        ("upload", "<binary>", 'filename="a.png"' + CRLF + "Content-Type: image/png"),
        ("message", "hello world", None),
    )
    fields = text_fields_in_body(body, MULTI)
    assert fields == {"message": "hello world"}


def test_multipart_nontext_content_type_fails_open():
    body = _multipart(("message", "data", "Content-Type: application/octet-stream"))
    assert text_fields_in_body(body, MULTI) == {}


def test_multipart_uses_the_substring_rule():
    body = _multipart(("message", "hello world", None))
    assert post_is_justified(body, MULTI, _typed("hello world")) is True
    assert post_is_justified(body, MULTI, _typed("hello")) is False
    assert post_is_justified(body, MULTI, []) is False


def test_multipart_value_whitespace_is_preserved():
    """The parser strips only the exact boundary CRLFs, never content."""
    body = _multipart(("message", "  spaced text  ", None))
    assert text_fields_in_body(body, MULTI) == {"message": "  spaced text  "}


def test_boundary_parameter_is_case_insensitive():
    """RFC 2046: Boundary=B is as legal as boundary=B."""
    body = _multipart(("message", "hello world", None))
    assert text_fields_in_body(body, "multipart/form-data; Boundary=B") == {
        "message": "hello world"
    }


def test_malformed_multipart_fails_open():
    assert text_fields_in_body(b"garbage no boundary parts", MULTI) == {}
    assert text_fields_in_body(b"--B", "multipart/form-data") == {}  # no boundary param


# ── parity with urlencoded ─────────────────────────────────────

def test_all_three_formats_agree_on_the_rule():
    cases = [
        (b"message=hello", FORM),
        (b'{"message": "hello"}', JSON),
        (_multipart(("message", "hello", None)), MULTI),
    ]
    for body, ct in cases:
        assert post_is_justified(body, ct, _typed("hello")) is True, ct
        assert post_is_justified(body, ct, _typed("x")) is False, ct
        assert post_is_justified(body, ct, []) is False, ct
