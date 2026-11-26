"""CLI: ``python -m feature_catalog check|build [--reports DIR] [--out DIR]``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .analysis import Analysis, load_and_analyse

LEVEL_LABEL = {"error": "FEHLER", "warning": "WARNUNG", "info": "HINWEIS"}


def _repo_root() -> Path:
    here = Path.cwd()
    for p in (here, *here.parents):
        if (p / "catalog" / "catalog.yaml").exists():
            return p
    return here


def print_findings(a: Analysis, show_info: bool) -> None:
    for f in sorted(a.findings, key=lambda f: ("error", "warning", "info").index(f.level)):
        if f.level == "info" and not show_info:
            continue
        where = f" [{f.where}]" if f.where else ""
        print(f"{LEVEL_LABEL[f.level]:8} {f.code:24} {f.message}{where}")


def summary(a: Analysis) -> str:
    total = sum(1 for r in a.features.values() if r.status != "prüfbestand")
    proven = sum(1 for r in a.features.values() if r.status == "nachgewiesen")
    review = sum(1 for r in a.features.values() if r.status == "prüfbestand")
    infos = sum(1 for f in a.findings if f.level == "info")
    mode = ("Testberichte: " + ", ".join(a.reports.files)) if a.reports and not a.reports.empty \
        else "nur statische Prüfung (ohne --reports werden Testergebnisse nicht bewertet)"
    return (f"{total} Features im Katalog, davon {proven} nachgewiesen · {review} im Prüfbestand · "
            f"{len(a.errors)} Fehler · {len(a.warnings)} Warnungen · {infos} Hinweise\n{mode}")


def review_table(a: Analysis) -> str:
    """Markdown table: criterion -> triggering action -> assertion (file:line)."""
    from .testbody import component_terms, endpoint_terms, review_lines

    root = a.loaded.root
    rows = ["| Feature | Kriterium | Test | Aktion (Zeile) | Zusicherung (Zeile) |", "|---|---|---|---|---|"]

    def cell(items):
        return "<br>".join(f"{n}: `{t[:70].replace('|', '/')}`" for n, t in items) or "–"

    for _, f in a.loaded.features:
        terms = set(f.technical.nodes) | {c.split()[-1] for c in f.technical.commands}
        for ep in f.technical.endpoints:
            terms |= endpoint_terms(ep)
        for comp in f.technical.components:
            terms |= set(component_terms(str(root / comp)))
        codes = {ac.id: ac.code for ac in f.acceptance}
        for ev in f.evidence:
            for crit in ev.covers:
                actions, asserts = review_lines(root, ev.file, ev.test, terms, codes.get(crit))
                rows.append(f"| {f.id} | {crit} | `{ev.file}` › {ev.test} | {cell(actions)} | {cell(asserts)} |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="feature_catalog", description="Feature-Katalog prüfen und erzeugen")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, help_text in (("check", "Katalog gegen Code und Testberichte prüfen"),
                            ("build", "Ansicht (HTML) und catalog.json erzeugen"),
                            ("review", "Nachweise als Tabelle Kriterium → Aktion → Zusicherung (Regel N7)")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--root", type=Path, default=None, help="Repository-Wurzel (Standard: automatisch)")
        p.add_argument("--reports", type=Path, default=None, help="Verzeichnis mit JUnit-XML-Berichten")
        p.add_argument("--hints", action="store_true", help="auch Hinweise ausgeben")
        if name == "build":
            p.add_argument("--out", type=Path, default=None, help="Zielordner (Standard: catalog/dist)")
    args = parser.parse_args(argv)

    root = (args.root or _repo_root()).resolve()
    if args.reports and not args.reports.exists():
        print(f"Berichtsverzeichnis {args.reports} existiert nicht", file=sys.stderr)
        return 2
    a = load_and_analyse(root, args.reports)
    if args.cmd == "review":
        print(review_table(a))
        return 0
    print_findings(a, args.hints)
    print(summary(a))
    if args.cmd == "build":
        from .view import write_view

        out = args.out.resolve() if args.out else root / "catalog" / "dist"
        paths = write_view(a, out)
        print("geschrieben: " + ", ".join(str(p.relative_to(root)) if p.is_relative_to(root) else str(p) for p in paths))
        return 0
    return 1 if a.errors else 0


if __name__ == "__main__":
    sys.exit(main())
