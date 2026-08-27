"""cadence command-line interface."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
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


def _mitmdump_argv(mitmdump: str, addon: str, host: str, port: int) -> list[str]:
    """Forward-proxy argv. Addon path is one element even if it contains spaces."""
    return [
        mitmdump,
        "-s",
        addon,
        "--listen-host",
        host,
        "--listen-port",
        str(port),
    ]


def _mitmdump_reverse_argv(
    mitmdump: str, addon: str, host: str, port: int, upstream: str
) -> list[str]:
    """Reverse-proxy argv: browsers hit host:port as a normal website."""
    return [
        mitmdump,
        "-s",
        addon,
        "--mode",
        f"reverse:{upstream}",
        "--listen-host",
        host,
        "--listen-port",
        str(port),
    ]


def _require_proxy() -> tuple[str, str]:
    try:
        addon = _addon_path()
    except (ImportError, OSError):
        sys.exit(
            "cadence: proxy addon missing — install the package (pip install .) or run from the repo"
        )
    mitmdump = shutil.which("mitmdump")
    if not mitmdump:
        print(
            'cadence: mitmdump not found. Install it with: pip install "cadence[proxy]"',
            file=sys.stderr,
        )
        sys.exit(2)
    return mitmdump, addon


def _run_mitmdump(argv: list[str]) -> None:
    # os.execv on Windows does not quote argv. pip's mitmdump.exe then
    # splits on spaces, so a path like COLLEGE PROJECTS becomes
    # "No such script: ...\COLLEGE". subprocess.call uses list2cmdline.
    if os.name == "nt":
        raise SystemExit(subprocess.call(argv))
    os.execv(argv[0], argv)


def _proxy(args) -> None:
    mitmdump, addon = _require_proxy()
    print(
        f"cadence proxy listening on http://{args.host}:{args.port} — point your browser proxy at it",
        file=sys.stderr,
    )
    _run_mitmdump(_mitmdump_argv(mitmdump, addon, args.host, args.port))


def _demo(args) -> None:
    """Form + reverse proxy. Open the printed URL in a normal browser."""
    mitmdump, addon = _require_proxy()
    from cadence.demo import bind_form_server, serve_in_thread

    httpd = bind_form_server("127.0.0.1")
    serve_in_thread(httpd)
    up_host, up_port = httpd.server_address[:2]
    upstream = f"http://{up_host}:{up_port}"
    print(
        f"cadence demo: open http://{args.host}:{args.port}/ in your normal browser\n"
        f"              no proxy settings, no special Chrome\n"
        f"              console: http://{args.host}:{args.port}/__cadence/console",
        file=sys.stderr,
    )
    argv = _mitmdump_reverse_argv(mitmdump, addon, args.host, args.port, upstream)
    # Always subprocess: execv would kill the form thread.
    raise SystemExit(subprocess.call(argv))


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
    except (ImportError, OSError) as exc:
        ok = False
        print(f"error   cannot resolve the edge package: {exc}")
    else:
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

    try:
        sys.path.insert(0, str(Path(_addon_path()).resolve().parent))
        import addon as addon_module  # noqa: E402  (resolves like mitmproxy would)

        from provenance import SESSION_COOKIE  # noqa: E402

        # Constants are imported and checked for agreement, not hardcoded:
        # the cookie name the addon mints must be the one provenance reads,
        # and neither may be empty. Renames are allowed; splits are not.
        if (
            SESSION_COOKIE
            and getattr(addon_module, "TELEMETRY_PATH", "")
            and addon_module.SESSION_COOKIE == SESSION_COOKIE
        ):
            print(f"ok      session cookie + telemetry path: {SESSION_COOKIE} / {addon_module.TELEMETRY_PATH}")
        else:
            ok = False
            print(
                f"error   wiring split: provenance cookie={SESSION_COOKIE!r} "
                f"addon cookie={getattr(addon_module, 'SESSION_COOKIE', None)!r}"
            )
    except (ImportError, OSError) as exc:
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

    demo = sub.add_parser(
        "demo",
        help="form + reverse proxy; open the printed URL in a normal browser",
    )
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8080)
    demo.set_defaults(func=_demo)

    doctor = sub.add_parser("doctor", help="check the proxy's prerequisites")
    doctor.set_defaults(func=_doctor)

    eval_parser = sub.add_parser("eval", help="replay a saved session through detectors + fusion")
    eval_parser.add_argument("session", help="session JSONL file to replay")

    def _eval(args):
        from cadence import eval as eval_module

        return eval_module.main([args.session])

    eval_parser.set_defaults(func=_eval)

    args = parser.parse_args(argv)
    result = args.func(args)
    if result is not None:
        sys.exit(result)


if __name__ == "__main__":
    main()
