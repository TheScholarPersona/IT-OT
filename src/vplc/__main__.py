"""Command line entry point: ``python -m vplc`` / ``vplc``."""

from __future__ import annotations

import argparse
import logging
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vplc", description="IT-OT virtuelle SPS")
    sub = parser.add_subparsers(dest="cmd")

    serve = sub.add_parser("serve", help="Manager mit REST-API und Weboberfläche starten")
    serve.add_argument("--host", default=os.environ.get("VPLC_HOST", "127.0.0.1"),
                       help="Adresse für die Weboberfläche (Standard: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=int(os.environ.get("VPLC_PORT", 8080)))
    serve.add_argument("--data", default=os.environ.get("VPLC_DATA", "data"),
                       help="Datenverzeichnis für Programme, Versionen und Audit-Log")

    check = sub.add_parser("check", help="Structured-Text- oder SCL-Datei (TIA Portal) prüfen")
    check.add_argument("file")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.cmd == "check":
        from .st import check_source
        from .st.parser import is_scl

        with open(args.file, encoding="utf-8-sig") as fh:  # TIA exports may carry a BOM
            source = fh.read()
        errors = check_source(source)
        for e in errors:
            print(f"{args.file}:{e['line']}:{e['col']}: {e['message']}")
        if not errors:
            print(f"{args.file}: OK" + (" (SCL)" if is_scl(source) else ""))
        return 1 if errors else 0

    if args.cmd == "serve" or args.cmd is None:
        import uvicorn

        from .manager.api import create_app

        host = getattr(args, "host", "127.0.0.1")
        port = getattr(args, "port", 8080)
        data = getattr(args, "data", "data")
        uvicorn.run(create_app(data_dir=data), host=host, port=port, log_level="info")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
