"""Compare the catalog with the code and the test results (rules of section 5.1).

The analysis only reports – it never creates or changes features.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .discover import (Discovered, call_matches, discover, endpoint_path, js_test_calls,
                       matches_prefix, python_test_calls)
from .junit import FAILED, NOT_RUN, PASSED, SKIPPED, Reports
from .loader import Finding, LoadedCatalog
from .schema import COMPONENT_KINDS, Feature
from .testbody import component_terms, endpoint_terms, read_test, touches

_CODE_IN_RULE = re.compile(r"`([0-9]{3,4}|[A-Z][A-Z0-9_]{2,}|[A-Z][A-Za-z]+(?:Error|Exception))`")


@dataclass
class EvidenceResult:
    file: str
    test: str
    kind: str
    covers: list[str]
    found: bool
    line: int
    has_assertion: bool
    status_only: bool
    related: bool
    outcome: str  # bestanden / fehlgeschlagen / übersprungen / nicht gelaufen / ungeprüft
    message: str = ""

    @property
    def valid(self) -> bool:
        return self.found and self.has_assertion and self.outcome in (PASSED, "ungeprüft")


@dataclass
class FeatureResult:
    status: str  # nachgewiesen | teilweise | statisch | prüfbestand
    evidence: list[EvidenceResult] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)  # acceptance ids
    callers: dict[str, list[str]] = field(default_factory=dict)  # endpoint -> tests calling it


@dataclass
class Analysis:
    loaded: LoadedCatalog
    discovered: Discovered
    reports: Reports | None
    findings: list[Finding] = field(default_factory=list)
    owner: dict[tuple[str, str], str | None] = field(default_factory=dict)  # (kind, item) -> area
    assigned: dict[tuple[str, str], list[str]] = field(default_factory=dict)  # -> feature ids
    features: dict[str, FeatureResult] = field(default_factory=dict)
    endpoint_callers: dict[str, list[str]] = field(default_factory=dict)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]


def rule_codes(rules: list[str]) -> list[str]:
    codes = []
    for r in rules:
        codes.extend(_CODE_IN_RULE.findall(r))
    return codes


def analyse(loaded: LoadedCatalog, reports: Reports | None = None,
            discovered: Discovered | None = None) -> Analysis:
    root = loaded.root
    cat = loaded.catalog
    disc = discovered if discovered is not None else (discover(root, cat.sources) if cat else Discovered())
    a = Analysis(loaded, disc, reports, list(loaded.findings))
    if cat is None:
        return a
    add = a.findings.append

    for p in disc.problems:
        add(Finding("SCHEMA", "error", p, "catalog.yaml#sources"))

    # ------------------------------------------------------------ structure
    areas = {ar.id: ar for ar in cat.areas}
    group_area = {g.id: ar.id for ar in cat.areas for g in ar.groups}
    all_features: list[tuple[str, Feature, bool]] = []  # (area, feature, in review)
    seen_ids: set[str] = set()
    for area_id, feat in loaded.features:
        all_features.append((area_id, feat, False))
    for feat in loaded.review:
        all_features.append((group_area.get(feat.group, ""), feat, True))
    for area_id, feat, in_review in all_features:
        where = f"{'review' if in_review else 'features'}:{feat.id}"
        if feat.id in seen_ids:
            add(Finding("SCHEMA", "error", f"Feature-ID {feat.id} ist doppelt", where))
        seen_ids.add(feat.id)
        if area_id not in areas:
            add(Finding("SCHEMA", "error", f"Unbekannter Bereich '{area_id}'", where))
        elif group_area.get(feat.group) != area_id:
            add(Finding("SCHEMA", "error", f"Gruppe '{feat.group}' gehört nicht zum Bereich '{area_id}'", where))
        if not feat.id.startswith(f"{area_id}."):
            add(Finding("SCHEMA", "error", f"Feature-ID muss mit '{area_id}.' beginnen", where))

    # ------------------------------------------------------------ ownership
    excluded = {(kind, e.item) for kind in COMPONENT_KINDS for e in getattr(cat.exclusions, kind)}
    for kind, items in disc.kinds().items():
        for item in items:
            key = item if kind != "endpoints" else endpoint_path(item)
            best, best_len, tie = None, -1, False
            for ar in cat.areas:
                for prefix in getattr(ar.owns, kind):
                    ok = matches_prefix(key, prefix) if kind in ("endpoints", "uiRoutes") else key == prefix
                    if ok:
                        if len(prefix) > best_len:
                            best, best_len, tie = ar.id, len(prefix), False
                        elif len(prefix) == best_len and ar.id != best:
                            tie = True
            a.owner[(kind, item)] = best
            if (kind, item) in excluded:
                continue
            if tie:
                add(Finding("SCHEMA", "error", f"{item} wird von mehreren Bereichen gleich lang beansprucht", kind))
            if best is None:
                add(Finding("UNOWNED", "error", f"{item} gehört zu keinem Bereich (owns.{kind})", kind))

    # ------------------------------------------------------------ references
    feature_ids = {f.id for _, f, _ in all_features}
    for area_id, feat, in_review in all_features:
        where = f"{'review' if in_review else 'features'}:{feat.id}"
        t = feat.technical
        for kind, code in (("endpoints", "UNKNOWN_ENDPOINT"), ("commands", "UNKNOWN_COMMAND"),
                           ("nodes", "UNKNOWN_NODE"), ("uiRoutes", "UNKNOWN_UIROUTE")):
            for item in getattr(t, kind):
                if item not in getattr(disc, kind):
                    add(Finding(code, "error", f"{item} existiert nicht (mehr)", where))
                else:
                    a.assigned.setdefault((kind, item), []).append(feat.id)
        for comp in t.components:
            if not (root / comp).exists():
                add(Finding("UNKNOWN_COMPONENT", "error", f"Quelldatei {comp} fehlt", where))
        for dep in feat.dependsOn:
            if dep not in feature_ids:
                add(Finding("UNKNOWN_DEPENDENCY", "error", f"dependsOn '{dep}' gibt es nicht", where))
    for kind in COMPONENT_KINDS:
        for e in getattr(cat.exclusions, kind):
            if e.item not in getattr(disc, kind):
                code = {"endpoints": "UNKNOWN_ENDPOINT", "commands": "UNKNOWN_COMMAND",
                        "nodes": "UNKNOWN_NODE", "uiRoutes": "UNKNOWN_UIROUTE"}[kind]
                add(Finding(code, "error", f"Ausnahme {e.item} existiert nicht (mehr)", "exclusions"))

    for kind, items in disc.kinds().items():
        for item in items:
            if (kind, item) in excluded or (kind, item) in a.assigned:
                continue
            area_id = a.owner.get((kind, item))
            if area_id is None:
                continue  # already UNOWNED
            level = "error" if areas[area_id].status == "katalogisiert" else "info"
            add(Finding("UNASSIGNED", level, f"{item} ist keinem Feature zugeordnet (Bereich {area_id})", kind))

    # ------------------------------------------------------------ endpoint calls in tests
    test_files = []
    for d in cat.sources.testDirs:
        base = root / d
        test_files += sorted(base.rglob("test_*.py")) + sorted(base.rglob("*_spec.js"))
    for tf in test_files:
        calls = python_test_calls(tf) if tf.suffix == ".py" else js_test_calls(tf)
        for method, path, line in calls:
            for ep in disc.endpoints:
                m, _, tpl = ep.partition(" ")
                if m == method and call_matches(path, tpl):
                    a.endpoint_callers.setdefault(ep, []).append(f"{tf.relative_to(root)}:{line}")
    for ep in disc.endpoints:
        if ("endpoints", ep) in excluded or ep in a.endpoint_callers:
            continue
        add(Finding("ENDPOINT_UNTESTED", "warning", f"Kein Test ruft {ep} erkennbar auf", "tests"))

    # ------------------------------------------------------------ evidence
    have_reports = reports is not None and not reports.empty
    for area_id, feat, in_review in all_features:
        where = f"{'review' if in_review else 'features'}:{feat.id}"
        result = FeatureResult("prüfbestand" if in_review else "nachgewiesen")
        a.features[feat.id] = result
        result.callers = {ep: a.endpoint_callers.get(ep, []) for ep in feat.technical.endpoints}
        acc_ids = {ac.id for ac in feat.acceptance}
        terms: set[str] = set()
        for ep in feat.technical.endpoints:
            terms |= endpoint_terms(ep)
        for comp in feat.technical.components:
            terms |= set(component_terms(str(root / comp)))
        terms |= set(feat.technical.nodes)
        terms |= {c.split()[-1] for c in feat.technical.commands}

        for ev in feat.evidence:
            body = read_test(root, ev.file, ev.test)
            outcome, message = "ungeprüft", ""
            if have_reports:
                outcome, message = reports.result(ev.file, ev.test)
            er = EvidenceResult(ev.file, ev.test, ev.kind, ev.covers, body.found, body.line,
                                body.has_assertion, body.status_only,
                                touches(body.text, terms) if body.found else False, outcome, message)
            result.evidence.append(er)
            label = f"{ev.file} › {ev.test}"
            if in_review:
                continue
            if not ev.covers or any(c not in acc_ids for c in ev.covers):
                add(Finding("EVIDENCE_UNLINKED", "error",
                            f"Nachweis {label}: covers fehlt oder nennt unbekannte Kriterien", where))
            if not body.found:
                add(Finding("UNKNOWN_TEST", "error", f"Test {label} nicht gefunden", where))
                continue
            if not body.has_assertion:
                add(Finding("EVIDENCE_NO_ASSERTION", "error", f"{label} enthält keine Zusicherung", where))
            elif body.status_only:
                add(Finding("EVIDENCE_STATUS_ONLY", "warning", f"{label} prüft nur Status/Existenz – Review nötig", where))
            if not er.related:
                add(Finding("EVIDENCE_UNRELATED", "warning",
                            f"{label} berührt keinen Bestandteil des Features – Review nötig", where))
            if outcome == FAILED:
                add(Finding("EVIDENCE_FAILED", "error", f"{label} ist fehlgeschlagen: {message}", where))
            elif outcome == SKIPPED:
                add(Finding("EVIDENCE_SKIPPED", "error", f"{label} wurde übersprungen", where))
            elif outcome == NOT_RUN:
                add(Finding("EVIDENCE_NOT_RUN", "error", f"{label} kommt in keinem Testbericht vor", where))

        if in_review:
            continue
        if not feat.evidence:
            add(Finding("EVIDENCE_MISSING", "error", "Feature ohne Nachweis", where))
        if not any(ac.kind == "effekt" for ac in feat.acceptance):
            add(Finding("ACCEPTANCE_MISSING", "error", "kein Akzeptanzkriterium der Art effekt", where))
        regel_codes = {ac.code for ac in feat.acceptance if ac.kind == "regel" and ac.code}
        for code in rule_codes(feat.rules):
            if code not in regel_codes:
                add(Finding("RULE_WITHOUT_ACCEPTANCE", "error",
                            f"Regel mit Fehlercode {code} hat kein Kriterium der Art regel", where))
        for ac in feat.acceptance:
            covering = [er for er in result.evidence if ac.id in er.covers and er.valid]
            if not covering:
                result.uncovered.append(ac.id)
                add(Finding("ACCEPTANCE_UNCOVERED", "error",
                            f"Kriterium '{ac.id}' hat keinen {'bestandenen ' if have_reports else ''}Nachweis", where))
            elif ac.kind == "regel" and ac.code:
                texts = [read_test(root, er.file, er.test).own_text for er in covering]
                if not any(ac.code in t for t in texts):
                    add(Finding("RULE_CODE_NOT_ASSERTED", "error",
                                f"Kriterium '{ac.id}': Code {ac.code} kommt in keinem abdeckenden Test vor", where))
        if result.uncovered or not feat.evidence or not feat.acceptance:
            result.status = "teilweise"
        elif not have_reports:
            result.status = "statisch"

    # ------------------------------------------------------------ comparisons
    for ref in cat.comparisons:
        comp = loaded.comparisons.get(ref.id)
        if comp is None:
            add(Finding("SCHEMA", "error", f"Vergleich {ref.id}: Datei comparisons/{ref.id}.yaml fehlt", "catalog.yaml"))
            continue
        topics = {t.id for t in comp.topics}
        for _, feat, in_review in all_features:
            topic = feat.comparisons.get(ref.id)
            if topic is None:
                if ref.complete:
                    add(Finding("COMPARISON_MISSING", "error",
                                f"keine Einstufung für Vergleich {ref.id}", f"features:{feat.id}"))
            elif topic not in topics:
                add(Finding("SCHEMA", "error", f"Vergleich {ref.id}: unbekanntes Thema '{topic}'",
                            f"features:{feat.id}"))
    return a


def load_and_analyse(root: Path, report_dir: Path | None = None) -> Analysis:
    from .junit import read_reports
    from .loader import load

    loaded = load(root)
    reports = read_reports(report_dir, root) if report_dir else None
    return analyse(loaded, reports)
