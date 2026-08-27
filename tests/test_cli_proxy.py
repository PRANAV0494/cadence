"""
cadence proxy / demo launch: Windows must keep a spaced addon path as one
argument; reverse mode is how a normal browser hits the demo.
"""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cadence import cli  # noqa: E402

SPACED_ADDON = r"C:\Users\prana\OneDrive\Desktop\COLLEGE PROJECTS\CADENCE\edge\addon.py"


def test_mitmdump_argv_keeps_spaces_in_addon_path():
    argv = cli._mitmdump_argv("mitmdump", SPACED_ADDON, "127.0.0.1", 8080)
    assert argv[1] == "-s"
    assert argv[2] == SPACED_ADDON


def test_windows_command_line_quotes_spaced_addon():
    argv = cli._mitmdump_argv(r"C:\Scripts\mitmdump.EXE", SPACED_ADDON, "127.0.0.1", 8080)
    line = subprocess.list2cmdline(argv)
    assert "COLLEGE PROJECTS" in line
    assert '"C:\\Users\\prana\\OneDrive\\Desktop\\COLLEGE PROJECTS\\CADENCE\\edge\\addon.py"' in line


def test_reverse_argv_is_a_website_not_a_browser_proxy():
    argv = cli._mitmdump_reverse_argv(
        "mitmdump", SPACED_ADDON, "127.0.0.1", 8080, "http://127.0.0.1:9"
    )
    assert "--mode" in argv
    assert argv[argv.index("--mode") + 1] == "reverse:http://127.0.0.1:9"
    assert argv[2] == SPACED_ADDON


def test_proxy_on_windows_uses_subprocess_not_execv(monkeypatch):
    monkeypatch.setattr(cli.os, "name", "nt")
    monkeypatch.setattr(cli.shutil, "which", lambda name: r"C:\Scripts\mitmdump.EXE")
    monkeypatch.setattr(cli, "_addon_path", lambda: SPACED_ADDON)
    seen = {}

    def fake_call(argv):
        seen["argv"] = argv
        return 0

    def boom(*_a, **_k):
        raise AssertionError("os.execv must not run on Windows")

    monkeypatch.setattr(cli.subprocess, "call", fake_call)
    monkeypatch.setattr(cli.os, "execv", boom)
    with pytest.raises(SystemExit) as exc:
        cli._proxy(SimpleNamespace(host="127.0.0.1", port=8080))
    assert exc.value.code == 0
    assert seen["argv"][2] == SPACED_ADDON


def test_cli_help_mentions_demo(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "demo" in capsys.readouterr().out
