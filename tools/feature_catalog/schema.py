"""Data model of the feature catalog (YAML is the single source of truth)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CHANNELS = ("web", "api", "s7", "opcua", "node-red", "cli", "entwicklung")
Channel = Literal["web", "api", "s7", "opcua", "node-red", "cli", "entwicklung"]
COMPONENT_KINDS = ("endpoints", "commands", "nodes", "uiRoutes")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------ catalog.yaml
class Owns(Strict):
    endpoints: list[str] = []  # path prefixes, e.g. "/api/plcs/{plc_id}/versions"
    commands: list[str] = []  # CLI commands, e.g. "vplc check"
    nodes: list[str] = []  # Node-RED node types
    uiRoutes: list[str] = []  # web UI routes, e.g. "/"


class Group(Strict):
    id: str
    title: str
    summary: str = ""


class Area(Strict):
    id: str
    title: str
    summary: str
    status: Literal["katalogisiert", "offen"] = "offen"
    owns: Owns = Owns()
    groups: list[Group] = []


class Exclusion(Strict):
    item: str
    reason: str


class Exclusions(Strict):
    endpoints: list[Exclusion] = []
    commands: list[Exclusion] = []
    nodes: list[Exclusion] = []
    uiRoutes: list[Exclusion] = []


class ComparisonRef(Strict):
    id: str
    title: str
    complete: bool = False  # true: every feature must be classified


class Sources(Strict):
    """Where discovery reads from (all paths relative to the repository root)."""

    routes: str | None = None  # JSON export written by a test (method, path, kind)
    cliModules: list[str] = []  # Python files with argparse sub-commands
    cliName: str = ""  # program name prefixed to sub-commands, e.g. "vplc"
    nodeRedFiles: list[str] = []  # JS files with RED.nodes.registerType / RED.httpAdmin
    testDirs: list[str] = []  # scanned for endpoint calls (ENDPOINT_UNTESTED)


class Catalog(Strict):
    schemaVersion: Literal[1]
    title: str = "Feature-Katalog"
    sources: Sources = Sources()
    areas: list[Area]
    exclusions: Exclusions = Exclusions()
    comparisons: list[ComparisonRef] = []


# ------------------------------------------------------------------ features
class Usage(Strict):
    channel: Channel
    text: str


class Technical(Strict):
    components: list[str] = []  # source files relative to the repository root
    endpoints: list[str] = []  # "METHOD /path", WebSocket: "WS /path"
    commands: list[str] = []
    nodes: list[str] = []
    uiRoutes: list[str] = []
    notes: list[str] = []


class Acceptance(Strict):
    id: str
    kind: Literal["effekt", "regel"]
    text: str
    code: str | None = None  # HTTP status, error code or exception class


class Evidence(Strict):
    kind: Literal["unit", "integration", "e2e"]
    file: str
    test: str  # pytest: function name or Class::function; mocha: it() title
    covers: list[str] = []


class Feature(Strict):
    id: str
    title: str
    group: str
    summary: str
    description: str = ""
    usage: list[Usage] = Field(min_length=1)
    rules: list[str] = []
    dependsOn: list[str] = []
    technical: Technical = Technical()
    acceptance: list[Acceptance] = []
    evidence: list[Evidence] = []
    comparisons: dict[str, str] = {}  # comparison id -> topic id


class ReviewFeature(Feature):
    state: Literal["unvollstaendig", "deaktiviert", "nicht-nachgewiesen"]
    reason: str


class FeatureFile(Strict):
    area: str
    features: list[Feature] = []


class ReviewFile(Strict):
    features: list[ReviewFeature] = []


# ------------------------------------------------------------------ comparisons
class Topic(Strict):
    id: str
    title: str
    status: Literal["vorhanden", "teilweise", "fehlt", "ohne-bezug"]
    summary: str = ""
    gaps: list[str] = []


class ComparisonFile(Strict):
    id: str
    title: str
    source: str = ""
    topics: list[Topic]
