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
    except (ImportError, OSError):
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


def _doctor(args) -> int:
    """Diagnose the proxy's prerequisites. Checks, prints, returns a code.

    Three things only: mitmdump on PATH, the edge files resolvable the way
    the proxy resolves them, and the addon's cookie/telemetry constants
    importable and mutually consistent. No fixes, no extra features.
    """
    ok = True

    mitmdump = shutil.which("mitmdump")
    if mitmdump:
        print(f"ok      mitmdump found: {mitmdump}")
    else:
        ok = False
        print('error   mitmdump not on PATH — pip install "cadence[proxy]"')

    try:
        addon = Path(_addon_path())
        if addon.is_file():
            print(f"ok      edge/addon.py resolves: {addon}")
        else:
            ok = False
            print(f"error   edge/addon.py resolved but missing: {addon}")
        sdk = addon.parent / "cadence-sdk.js"
        if sdk.is_file():
            print(f"ok      edge/cadence-sdk.js present: {sdk}")
        else:
            ok = False
            print(f"error   edge/cadence-sdk.js missing beside the addon: {sdk}")
    except Exception as exc:
        ok = False
        print(f"error   cannot resolve the edge package: {exc}")

    try:
        sys.path.insert(0, str(Path(_addon_path()).resolve().parent))
        import addon as addon_module  # noqa: E402  (resolves like mitmproxy would)

        from provenance import SESSION_COOKIE  # noqa: E402

        if SESSION_COOKIE == "__cadence_sid" and addon_module.TELEMETRY_PATH == "/__cadence/telemetry":
            print(f"ok      session cookie + telemetry path: {SESSION_COOKIE} / {addon_module.TELEMETRY_PATH}")
        else:
            ok = False
            print(
                f"error   unexpected wiring: cookie={SESSION_COOKIE} "
                f"path={addon_module.TELEMETRY_PATH}"
            )
    except Exception as exc:
        ok = False
        print(f"error   addon import failed: {exc}")

    print("cadence doctor: " + ("all checks passed" if ok else "problems found"))
    return 0 if ok else 1


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="cadence")
    sub = parser.add_subparsers(dest="command", required=True)

    proxy = sub.add_parser("proxy", help="run the mitmproxy addon that injects cadence-sdk.js")
    proxy.add_argument("--host", default="127.0.0.1")
    proxy.add_argument("--port", type=int, default=8080)
    proxy.set_defaults(func=_proxy)

    doctor = sub.add_parser("doctor", help="check the proxy's prerequisites")
    doctor.set_defaults(func=_doctor)

    args = parser.parse_args(argv)
    result = args.func(args)
    if result is not None:
        sys.exit(result)


if __name__ == "__main__":
    main()
