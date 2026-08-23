"""cadence command-line interface."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path


def _proxy(args) -> None:
    addon = Path(__file__).resolve().parents[1] / "edge" / "addon.py"
    if not addon.is_file():
        sys.exit(f"cadence: proxy addon missing: {addon}")
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
            str(addon),
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
