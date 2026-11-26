"""Load and validate the YAML files under ``catalog/``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from .schema import Catalog, ComparisonFile, Feature, FeatureFile, ReviewFeature, ReviewFile


@dataclass
class Finding:
    code: str
    level: str  # "error" | "warning" | "info"
    message: str
    where: str = ""

    def to_dict(self) -> dict:
        return {"code": self.code, "level": self.level, "message": self.message, "where": self.where}


@dataclass
class LoadedCatalog:
    root: Path  # repository root
    catalog: Catalog | None = None
    features: list[tuple[str, Feature]] = field(default_factory=list)  # (area id, feature)
    review: list[ReviewFeature] = field(default_factory=list)
    comparisons: dict[str, ComparisonFile] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)


def _read_yaml(path: Path, findings: list[Finding]):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        findings.append(Finding("SCHEMA", "error", f"YAML ungültig: {e}", str(path)))
        return None


def _validate(model, data, path: Path, findings: list[Finding]):
    try:
        return model.model_validate(data)
    except ValidationError as e:
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            findings.append(Finding("SCHEMA", "error", f"{loc}: {err['msg']}", str(path)))
        return None


def load(root: Path, catalog_dir: str = "catalog") -> LoadedCatalog:
    root = Path(root)
    base = root / catalog_dir
    result = LoadedCatalog(root=root)
    f = result.findings

    data = _read_yaml(base / "catalog.yaml", f)
    if data is not None:
        result.catalog = _validate(Catalog, data, base / "catalog.yaml", f)

    for path in sorted((base / "features").glob("*.yaml")):
        data = _read_yaml(path, f)
        if data is None:
            continue
        ff = _validate(FeatureFile, data, path, f)
        if ff:
            result.features.extend((ff.area, feat) for feat in ff.features)

    review_path = base / "review.yaml"
    if review_path.exists():
        data = _read_yaml(review_path, f)
        if data is not None:
            rf = _validate(ReviewFile, data, review_path, f)
            if rf:
                result.review = rf.features

    for path in sorted((base / "comparisons").glob("*.yaml")):
        data = _read_yaml(path, f)
        if data is None:
            continue
        cf = _validate(ComparisonFile, data, path, f)
        if cf:
            result.comparisons[cf.id] = cf
    return result
