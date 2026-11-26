"""Generate catalog.json and a self-contained HTML view (no server, no external scripts)."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .analysis import Analysis
from .schema import COMPONENT_KINDS

TEMPLATE = Path(__file__).with_name("template.html")


def catalog_data(a: Analysis) -> dict:
    loaded, cat, disc = a.loaded, a.loaded.catalog, a.discovered
    group_area = {g.id: ar.id for ar in cat.areas for g in ar.groups}
    features = []
    entries = [(area, f, False) for area, f in loaded.features] + \
              [(group_area.get(f.group, ""), f, True) for f in loaded.review]
    for area_id, f, in_review in entries:
        res = a.features.get(f.id)
        d = f.model_dump()
        d["area"] = area_id
        d["inReview"] = in_review
        d["status"] = res.status if res else "teilweise"
        d["uncovered"] = res.uncovered if res else []
        d["evidenceResults"] = [asdict(e) for e in res.evidence] if res else []
        d["endpointInfo"] = [
            {"id": ep, "summary": disc.endpoints.get(ep, ""), "callers": (res.callers.get(ep, []) if res else [])}
            for ep in f.technical.endpoints
        ]
        d["findings"] = [x.to_dict() for x in a.findings if x.where.endswith(":" + f.id)]
        features.append(d)

    unassigned = []
    for kind, items in disc.kinds().items():
        excluded = {e.item for e in getattr(cat.exclusions, kind)}
        for item in items:
            if (kind, item) not in a.assigned and item not in excluded:
                unassigned.append({"kind": kind, "item": item, "area": a.owner.get((kind, item))})

    comparisons = []
    for ref in cat.comparisons:
        comp = loaded.comparisons.get(ref.id)
        if not comp:
            continue
        topics = []
        for t in comp.topics:
            td = t.model_dump()
            td["features"] = [x["id"] for x in features if x["comparisons"].get(ref.id) == t.id]
            topics.append(td)
        comparisons.append({"id": ref.id, "title": comp.title, "source": comp.source, "topics": topics})

    in_catalog = [x for x in features if not x["inReview"]]
    return {
        "title": cat.title,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reports": a.reports.files if a.reports and not a.reports.empty else [],
        "stats": {
            "features": len(in_catalog),
            "proven": sum(1 for x in in_catalog if x["status"] == "nachgewiesen"),
            "review": len(features) - len(in_catalog),
            "areas": len(cat.areas),
            "areasDone": sum(1 for ar in cat.areas if ar.status == "katalogisiert"),
            "errors": len(a.errors),
            "warnings": len(a.warnings),
            "criteria": sum(len(x["acceptance"]) for x in in_catalog),
            "evidence": sum(len(x["evidence"]) for x in in_catalog),
            "components": sum(len(v) for v in disc.kinds().values()),
        },
        "areas": [ar.model_dump() for ar in cat.areas],
        "features": features,
        "exclusions": {k: [e.model_dump() for e in getattr(cat.exclusions, k)] for k in COMPONENT_KINDS},
        "unassigned": unassigned,
        "comparisons": comparisons,
        "findings": [x.to_dict() for x in a.findings],
    }


def render_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return TEMPLATE.read_text(encoding="utf-8").replace("/*__CATALOG_DATA__*/null", payload)


def write_view(a: Analysis, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    data = catalog_data(a)
    json_path = out / "catalog.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path = out / "index.html"
    html_path.write_text(render_html(data), encoding="utf-8")
    return [html_path, json_path]
