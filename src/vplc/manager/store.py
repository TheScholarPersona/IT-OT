"""File based persistence: PLC configurations, program versions and audit log.

Layout of the data directory::

    plcs.json                    PLC configurations and desired state
    programs/<plc-id>/<n>.json   program versions (source, author, comment, hash)
    audit.jsonl                  append-only audit trail
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class ProgramVersion:
    version: int
    source: str
    author: str
    comment: str
    created: str
    sha256: str
    program_name: str

    def meta(self) -> dict:
        d = asdict(self)
        d.pop("source")
        return d


class Store:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "programs").mkdir(exist_ok=True)
        self._lock = threading.Lock()

    # ------------------------------------------------------------ helpers
    def _write_json(self, path: Path, data) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)  # atomic on POSIX

    # ------------------------------------------------------------ PLCs
    def load_plcs(self) -> list[dict]:
        path = self.root / "plcs.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def save_plcs(self, plcs: list[dict]) -> None:
        with self._lock:
            self._write_json(self.root / "plcs.json", plcs)

    def delete_programs(self, plc_id: str) -> None:
        folder = self.root / "programs" / plc_id
        if folder.exists():
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()

    # ------------------------------------------------------------ program versions
    def _program_dir(self, plc_id: str) -> Path:
        d = self.root / "programs" / plc_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def list_versions(self, plc_id: str) -> list[ProgramVersion]:
        d = self.root / "programs" / plc_id
        if not d.exists():
            return []
        versions = []
        for f in d.glob("*.json"):
            versions.append(ProgramVersion(**json.loads(f.read_text(encoding="utf-8"))))
        return sorted(versions, key=lambda v: v.version)

    def get_version(self, plc_id: str, version: int) -> ProgramVersion | None:
        f = self.root / "programs" / plc_id / f"{version}.json"
        if not f.exists():
            return None
        return ProgramVersion(**json.loads(f.read_text(encoding="utf-8")))

    def add_version(self, plc_id: str, source: str, author: str, comment: str,
                    program_name: str) -> ProgramVersion:
        with self._lock:
            existing = self.list_versions(plc_id)
            number = existing[-1].version + 1 if existing else 1
            pv = ProgramVersion(
                version=number,
                source=source,
                author=author,
                comment=comment,
                created=now_iso(),
                sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
                program_name=program_name,
            )
            self._write_json(self._program_dir(plc_id) / f"{number}.json", asdict(pv))
            return pv

    # ------------------------------------------------------------ audit
    def audit(self, user: str, action: str, plc_id: str | None = None, **details) -> dict:
        entry = {"ts": now_iso(), "user": user, "action": action, "plc_id": plc_id, **details}
        with self._lock:
            with open(self.root / "audit.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def read_audit(self, plc_id: str | None = None, limit: int = 200) -> list[dict]:
        path = self.root / "audit.jsonl"
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            if plc_id is None or e.get("plc_id") == plc_id:
                entries.append(e)
        return list(reversed(entries[-limit:]))
