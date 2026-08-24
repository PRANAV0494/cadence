"""
cadence doctor tests: three checks, honest exit codes, no side effects.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cadence import cli  # noqa: E402


def test_doctor_all_good(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/mitmdump")
    code = cli._doctor(None)
    out = capsys.readouterr().out
    assert code == 0
    assert "all checks passed" in out
    assert "mitmdump found" in out
    assert "edge/addon.py resolves" in out
    assert "session cookie + telemetry path" in out


def test_doctor_fails_without_mitmdump(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda name: None)
    code = cli._doctor(None)
    out = capsys.readouterr().out
    assert code == 1
    assert "problems found" in out
    assert 'pip install "cadence[proxy]"' in out


def test_doctor_reports_missing_sdk(monkeypatch, capsys, tmp_path):
    """edge/ present but cadence-sdk.js gone: the file check fails loudly."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/mitmdump")
    import edge as edge_pkg

    real = Path(edge_pkg.__file__).resolve().parent
    fake = tmp_path / "edge"
    fake.mkdir()
    (fake / "addon.py").write_text(
        "TELEMETRY_PATH = '/__cadence/telemetry'\n", encoding="utf-8"
    )
    monkeypatch.setattr(cli, "_addon_path", lambda: str(fake / "addon.py"))
    code = cli._doctor(None)
    out = capsys.readouterr().out
    assert code == 1
    assert "cadence-sdk.js missing" in out


def test_doctor_is_listed_in_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "doctor" in capsys.readouterr().out
