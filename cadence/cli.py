"""cadence command-line interface."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def _addon_path() -> str:
    """Real filesystem path of edge/addon.py.

    Works in a checkout (edge/ beside the package) and after
    pip install . (edge/ is an installed package whose .js/.py files are
    package data). mitmproxy's -s flag needs an actual file, so the data
    must be installed, not merely importable.
    """
    try:
        import edge  # installed package, or the repo's edge/ on sys.path
    except ImportError as exc:
        raise ImportError(
            "the edge package is not installed; run from the repo or pip install ."
        ) from exc
    addon = Path(edge.__file__).resolve().parent / "addon.py"
    if not addon.is_file():
        raise OSError(f"edge package has no addon.py: {addon}")
    return str(addon)


def _proxy(args) -> None:
    try:
        addon = _addon_path()
    except Exception:
        sys.exit("cadence: proxy addon missing — install the package (pip install .) or run from the repo")
    mitmdump = shutil.which("mitmdump")
    if not mitmdump:
        print('cadence: mitmdump not found. Install it with: pip install "cadence[proxy]"', file=sys.stderr)
        sys.exit(2)
    print(
        f"cadence proxy listening on http://{args.host}:{args.port} — point your browser proxy at it",
        file=sys.stderr,
    )
    os.execv(
        mitmdump,
        [
            mitmdump,
            "-s",
            addon,
            "--listen-host",
            args.host,
            "--listen-port",
            str(args.port),
        ],
    )


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="cadence")
    sub = parser.add_subparsers(dest="command", required=True)

    proxy = sub.add_parser("proxy", help="run the mitmproxy addon that injects cadence-sdk.js")
    proxy.add_argument("--host", default="127.0.0.1")
    proxy.add_argument("--port", type=int, default=8080)
    proxy.set_defaults(func=_proxy)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
