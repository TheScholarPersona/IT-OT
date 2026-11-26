"""Read JUnit XML reports (pytest, mocha-junit-reporter) and look up test results."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

PASSED, FAILED, SKIPPED, NOT_RUN = "bestanden", "fehlgeschlagen", "übersprungen", "nicht gelaufen"


@dataclass
class Case:
    file: str | None  # repository-relative file (mocha) or None (pytest: derived from classname)
    classname: str
    name: str
    outcome: str
    message: str = ""


@dataclass
class Reports:
    cases: list[Case] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.files

    def _python_cases(self, module: str):
        for c in self.cases:
            if c.file is None and (c.classname == module or c.classname.startswith(module + ".")):
                yield c

    def ran_file(self, file: str) -> bool:
        if file.endswith(".py"):
            return any(True for _ in self._python_cases(_module_of(file)))
        return any(c.file == file for c in self.cases)

    def result(self, file: str, test: str) -> tuple[str, str]:
        """Outcome of one test; parametrised instances must all pass."""
        if file.endswith(".py"):
            module = _module_of(file)
            cls, _, func = test.rpartition("::")
            matches = [c for c in self._python_cases(module)
                       if _strip_param(c.name) == func
                       and (not cls or c.classname.endswith("." + cls))]
        else:
            matches = [c for c in self.cases if c.file == file and (c.classname == test or c.name.endswith(" " + test))]
        if not matches:
            return NOT_RUN, ""
        for outcome in (FAILED, SKIPPED):
            bad = [m for m in matches if m.outcome == outcome]
            if bad:
                return outcome, bad[0].message
        return PASSED, ""


def _module_of(file: str) -> str:
    return file[:-3].replace("/", ".").replace("\\", ".")


def _strip_param(name: str) -> str:
    return re.sub(r"\[.*\]$", "", name)


def read_reports(report_dir: Path, root: Path) -> Reports:
    reports = Reports()
    root = Path(root).resolve()
    for path in sorted(Path(report_dir).glob("*.xml")):
        try:
            tree = ET.parse(path)
        except ET.ParseError:
            continue
        reports.files.append(path.name)
        for suite in tree.iter("testsuite"):
            suite_file = suite.get("file")
            rel = None
            if suite_file:
                p = Path(suite_file)
                try:
                    rel = str(p.resolve().relative_to(root)) if p.is_absolute() else suite_file
                except ValueError:
                    rel = suite_file
            for case in suite.findall("testcase"):
                outcome, message = PASSED, ""
                for tag, value in (("failure", FAILED), ("error", FAILED), ("skipped", SKIPPED)):
                    el = case.find(tag)
                    if el is not None:
                        outcome, message = value, (el.get("message") or "")[:300]
                        break
                reports.cases.append(Case(rel, case.get("classname", ""), case.get("name", ""), outcome, message))
    return reports
