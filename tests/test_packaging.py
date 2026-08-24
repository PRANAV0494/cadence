"""
Packaging tests: `cadence proxy` must find the addon after pip install .,
not only in a checkout. The wheel must carry edge/ (the review finding on
PR #8 — site-packages has no edge/ next to cadence/).
"""

import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_addon_path_resolves_in_the_checkout():
    from cadence import cli

    addon = Path(cli._addon_path())
    assert addon.is_file()
    assert addon.name == "addon.py"
    assert addon.parent.name == "edge"


def test_addon_path_resolves_via_import_even_when_cwd_moves(monkeypatch, tmp_path):
    """Resolution goes through the edge package, not the CWD or __file__
    layout guessing."""
    from cadence import cli

    monkeypatch.chdir(tmp_path)
    addon = Path(cli._addon_path())
    assert addon.is_file()


def test_wheel_contains_the_edge_files(tmp_path):
    """Build the wheel and list it: the .js SDK and the addon must be
    inside, or pip install . cannot work."""
    import subprocess

    out = tmp_path / "dist"
    build = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(out), str(REPO)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    wheels = list(out.glob("*.whl"))
    assert wheels, f"wheel build failed: {build.stderr[-400:]}"
    names = set(zipfile.ZipFile(wheels[0]).namelist())
    # Assert only what exists on main today. Files landing in later PRs
    # (automation/drift/fusion) enter this list when their PRs merge —
    # asserting them now would fail the retargeted base.
    for needed in (
        "edge/__init__.py",
        "edge/addon.py",
        "edge/inject.py",
        "edge/cadence-sdk.js",
        "edge/provenance.py",
    ):
        assert needed in names, f"{needed} missing from wheel"
