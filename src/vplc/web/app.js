"use strict";

const $ = (sel) => document.querySelector(sel);
const state = { plcs: [], current: null, tab: "program", errors: [], dirty: false, info: null };

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (_) { return null; }
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) {
    if (c === null || c === undefined) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function toast(message, isError = false) {
  const t = $("#toast");
  t.textContent = message;
  t.className = "toast" + (isError ? " error" : "");
  t.hidden = false;
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => { t.hidden = true; }, isError ? 6000 : 2500);
}

async function api(method, path, body, { text = false } = {}) {
  const headers = { "X-User": $("#user").value.trim() || "anonymous" };
  const token = $("#token").value;
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 204) return null;
  if (!res.ok) {
    let data = {};
    try { data = await res.json(); } catch (_) { /* not JSON */ }
    const err = new Error(typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`);
    err.status = res.status;
    err.errors = data.errors;
    throw err;
  }
  return text ? res.text() : res.json();
}

function fmtScalar(x) {
  if (typeof x === "boolean") return x ? "TRUE" : "FALSE";
  if (typeof x === "number" && !Number.isInteger(x)) return Number(x.toPrecision(7)).toString();
  return String(x);
}

function fmtAny(x) {
  if (Array.isArray(x)) return "[" + x.map(fmtAny).join(", ") + "]";
  if (x && typeof x === "object") return "{" + Object.entries(x).map(([k, y]) => `${k}: ${fmtAny(y)}`).join(", ") + "}";
  if (typeof x === "string") return JSON.stringify(x);
  return fmtScalar(x);
}

function fmtValue(v) {
  if (v.display) return v.display;
  if (Array.isArray(v.value) || (v.value && typeof v.value === "object")) return fmtAny(v.value);
  if (typeof v.value === "boolean") return v.value ? "TRUE" : "FALSE";
  if (typeof v.value === "number" && !Number.isInteger(v.value)) return Number(v.value.toPrecision(7)).toString();
  return String(v.value);
}

// ------------------------------------------------------------------ PLC list
async function loadPlcs() {
  try {
    state.plcs = await api("GET", "/api/plcs");
  } catch (e) {
    if (e.status === 401) { $("#token-label").hidden = false; }
    return;
  }
  const list = $("#plc-list");
  list.replaceChildren(...state.plcs.map((p) => el("li", {
    class: p.id === state.current ? "active" : "",
    onclick: () => select(p.id),
  }, el("span", { class: "name", title: p.name }, p.name), el("span", { class: `dot ${p.mode}`, title: p.mode }))));
  $("#plc-empty").hidden = state.plcs.length > 0;
  if (!state.current) {
    $("#welcome").hidden = false;
    $("#detail").hidden = true;
  }
}

async function select(id) {
  if (state.dirty && state.current !== id && !confirm("Ungespeicherte Änderungen im Editor verwerfen?")) return;
  state.current = id;
  state.dirty = false;
  store("vplc.current", id);
  $("#welcome").hidden = true;
  $("#detail").hidden = false;
  $("#diff").hidden = true;
  await Promise.all([loadPlcs(), refreshStatus(), loadProgram()]);
  showTab(state.tab);
}

// ------------------------------------------------------------------ status
async function refreshStatus() {
  if (!state.current) return;
  let s;
  try {
    s = await api("GET", `/api/plcs/${state.current}`);
  } catch (e) {
    if (e.status === 404) { state.current = null; loadPlcs(); }
    return;
  }
  $("#d-name").textContent = s.name;
  const mode = $("#d-mode");
  mode.textContent = s.mode;
  mode.className = `badge ${s.mode}`;
  $("#d-program").textContent = s.program ? `${s.program}${s.dialect === "SCL" ? " (SCL)" : ""} · Version ${s.program_version ?? "–"} · Zyklus ${s.cycle_ms} ms` : "kein Programm geladen";
  $("#btn-run").disabled = s.mode === "RUN" || !s.program;
  $("#btn-stop").disabled = s.mode !== "RUN";
  $("#s-scans").textContent = s.scan_count.toLocaleString("de-DE");
  $("#s-cycle").textContent = s.scan_count ? `${s.avg_scan_us.toFixed(0)} µs / ${s.max_scan_us.toFixed(0)} µs` : "–";
  $("#s-overruns").textContent = s.overruns;
  $("#c-s7").textContent = s.s7.enabled
    ? `${location.hostname}:${s.s7.port} · Rack 0 · Slot 1 · DB${s.s7.db} (${s.s7.db_size} Byte)${s.s7.error ? " – " + s.s7.error : ""}`
    : "deaktiviert";
  $("#c-ua").textContent = s.opcua.enabled
    ? `opc.tcp://${location.hostname}:${s.opcua.port}/vplc/${s.opcua.error ? " – " + s.opcua.error : ""}`
    : "deaktiviert";
  const errBox = $("#d-error");
  if (s.last_error) {
    errBox.hidden = false;
    errBox.textContent = `STOP wegen Laufzeitfehler: ${s.last_error.message}` + (s.last_error.line ? ` (Zeile ${s.last_error.line})` : "");
  } else {
    errBox.hidden = true;
  }
  if (state.tab === "diagnostics") renderDiag(s.diagnostics);
  const dot = document.querySelector(".plc-list li.active .dot");
  if (dot) dot.className = `dot ${s.mode}`;
}

function renderDiag(entries) {
  $("#diag").replaceChildren(...entries.map((d) => el("li", { class: d.level },
    `${new Date(d.ts).toLocaleString("de-DE")}  ${d.level.toUpperCase().padEnd(7)} ${d.message}${d.line ? ` (Zeile ${d.line})` : ""}`)));
}

// ------------------------------------------------------------------ editor
function renderGutter() {
  const lines = $("#source").value.split("\n").length;
  const errLines = new Set(state.errors.map((e) => e.line));
  const frag = document.createDocumentFragment();
  for (let i = 1; i <= lines; i++) {
    frag.append(errLines.has(i) ? el("span", { class: "err" }, String(i)) : String(i), "\n");
  }
  $("#gutter").replaceChildren(frag);
  $("#gutter").scrollTop = $("#source").scrollTop;
}

function renderErrors(errors, okText) {
  state.errors = errors || [];
  const list = $("#errors");
  if (!state.errors.length) {
    list.replaceChildren(okText ? el("li", { class: "ok" }, okText) : "");
  } else {
    list.replaceChildren(...state.errors.map((e) => el("li", {
      onclick: () => jumpTo(e.line, e.col),
    }, `Zeile ${e.line ?? "?"}, Spalte ${e.col ?? "?"}: ${e.message}`)));
  }
  renderGutter();
}

function jumpTo(line, col) {
  const ta = $("#source");
  const lines = ta.value.split("\n");
  let pos = 0;
  for (let i = 0; i < (line || 1) - 1 && i < lines.length; i++) pos += lines[i].length + 1;
  pos += Math.max(0, (col || 1) - 1);
  ta.focus();
  ta.setSelectionRange(pos, pos);
  const lineHeight = parseFloat(getComputedStyle(ta).lineHeight) || 19;
  ta.scrollTop = Math.max(0, (line - 5) * lineHeight);
}

async function loadProgram() {
  const p = await api("GET", `/api/plcs/${state.current}/program`);
  $("#source").value = p.source || "PROGRAM Main\nVAR\n  Zaehler : INT;\nEND_VAR\n\nZaehler := Zaehler + 1;\nEND_PROGRAM\n";
  state.dirty = false;
  renderErrors([]);
}

async function checkProgram() {
  const r = await api("POST", "/api/check", { source: $("#source").value });
  renderErrors(r.errors, r.ok ? (r.dialect === "SCL" ? "✓ Keine Fehler gefunden (SCL aus TIA Portal erkannt)" : "✓ Keine Fehler gefunden") : null);
  return r.ok;
}

async function downloadProgram() {
  try {
    const r = await api("PUT", `/api/plcs/${state.current}/program`, {
      source: $("#source").value,
      comment: $("#commit-msg").value,
      warm: $("#warm").checked,
    });
    state.dirty = false;
    $("#commit-msg").value = "";
    renderErrors([], `✓ Version ${r.version.version} geladen`);
    toast(`Programm als Version ${r.version.version} geladen`);
    refreshStatus();
    loadPlcs();
  } catch (e) {
    if (e.errors) renderErrors(e.errors);
    toast(e.message, true);
  }
}

// ------------------------------------------------------------------ variables
async function refreshVariables() {
  if (!state.current || state.tab !== "variables") return;
  let vars;
  try { vars = await api("GET", `/api/plcs/${state.current}/variables`); } catch (_) { return; }
  const filter = $("#var-filter").value.trim().toLowerCase();
  const showFb = $("#show-fb").checked;
  const body = $("#var-body");
  const focused = document.activeElement && document.activeElement.closest("#var-body") ? document.activeElement.dataset.var : null;
  if (focused) {
    // Keep the row the user is editing; only update values of other rows.
    for (const v of vars) {
      const cell = body.querySelector(`td.value[data-var="${CSS.escape(v.name)}"]`);
      if (cell) { cell.textContent = fmtValue(v); cell.classList.toggle("true", v.value === true); }
    }
    return;
  }
  body.replaceChildren(...vars
    .filter((v) => showFb || !v.name.includes("."))
    .filter((v) => !filter || v.name.toLowerCase().includes(filter))
    .map((v) => el("tr", {},
      el("td", {}, v.name),
      el("td", {}, v.type),
      el("td", { class: "muted" }, v.constant ? "CONSTANT" : v.section),
      el("td", { class: `value${v.value === true ? " true" : ""}`, "data-var": v.name }, fmtValue(v)),
      el("td", {}, v.s7_address ? el("code", {}, v.s7_address) : ""),
      el("td", {}, v.opcua_node ? el("code", {}, v.opcua_node) : ""),
      el("td", {}, v.writable ? writeControl(v) : ""),
    )));
}

function writeControl(v) {
  if (v.type === "BOOL") {
    return el("button", { class: "small", onclick: () => writeVar(v.name, !v.value) }, v.value ? "→ FALSE" : "→ TRUE");
  }
  const placeholder = Array.isArray(v.value) ? "[1, 2, …]" : v.value && typeof v.value === "object" ? '{"Feld": …}' : "Wert";
  const input = el("input", { type: "text", placeholder, "data-var": v.name,
    onkeydown: (ev) => { if (ev.key === "Enter") submit(); } });
  const submit = () => {
    const raw = input.value.trim();
    if (!raw) return;
    let value;
    if (raw.startsWith("[") || raw.startsWith("{")) {
      // whole array [1, 2, 3] or (partial) struct {"Menge": 5}; TRUE/FALSE as in ST
      try { value = JSON.parse(raw.replace(/\bTRUE\b/gi, "true").replace(/\bFALSE\b/gi, "false")); }
      catch (_) { toast('Nicht lesbar – Beispiele: [1, 2, 3] oder {"Menge": 5}', true); return; }
    } else if (v.type.startsWith("STRING")) {
      value = raw;  // text stays text, even if it looks like a number
    } else {
      const num = Number(raw.replace(",", "."));
      value = Number.isFinite(num) ? num : raw;
    }
    writeVar(v.name, value).then(() => { input.value = ""; input.blur(); });
  };
  return el("span", {}, input, " ", el("button", { class: "small", onclick: submit }, "Setzen"));
}

async function writeVar(name, value) {
  try {
    await api("PUT", `/api/plcs/${state.current}/variables/${encodeURIComponent(name)}`, { value });
    refreshVariables();
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ versions
async function loadVersions() {
  const versions = await api("GET", `/api/plcs/${state.current}/versions`);
  const status = state.plcs.find((p) => p.id === state.current) || {};
  $("#ver-body").replaceChildren(...versions.map((v, i) => el("tr", {},
    el("td", {}, `v${v.version}`, v.version === status.program_version ? el("span", { class: "muted" }, " (aktiv)") : null),
    el("td", {}, new Date(v.created).toLocaleString("de-DE")),
    el("td", {}, v.author),
    el("td", {}, v.comment || el("span", { class: "muted" }, "–")),
    el("td", {}, el("span", { class: "hash", title: v.sha256 }, v.sha256.slice(0, 12))),
    el("td", {},
      versions[i + 1] ? el("button", { class: "small", onclick: () => showDiff(versions[i + 1].version, v.version) }, "Diff") : null, " ",
      el("button", { class: "small", onclick: () => openVersion(v.version) }, "Im Editor"), " ",
      el("button", { class: "small", onclick: () => activate(v.version) }, "Aktivieren"),
    ),
  )));
  if (!versions.length) $("#ver-body").replaceChildren(el("tr", {}, el("td", { colspan: 6, class: "muted" }, "Noch keine Versionen.")));
}

async function showDiff(a, b) {
  const text = await api("GET", `/api/plcs/${state.current}/diff?a=${a}&b=${b}`, undefined, { text: true });
  const pre = $("#diff");
  pre.replaceChildren(...text.split("\n").map((line) => el("span", {
    class: line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : "",
  }, line + "\n")));
  if (!text) pre.textContent = "Keine Unterschiede.";
  pre.hidden = false;
}

async function openVersion(version) {
  if (state.dirty && !confirm("Ungespeicherte Änderungen im Editor verwerfen?")) return;
  const v = await api("GET", `/api/plcs/${state.current}/versions/${version}`);
  $("#source").value = v.source;
  state.dirty = true;
  renderErrors([]);
  showTab("program");
}

async function activate(version) {
  if (!confirm(`Version ${version} in die vPLC laden?`)) return;
  try {
    await api("POST", `/api/plcs/${state.current}/versions/${version}/activate`);
    toast(`Version ${version} aktiviert`);
    await Promise.all([loadPlcs(), refreshStatus(), loadProgram()]);
    loadVersions();
  } catch (e) { toast(e.message, true); }
}

// ------------------------------------------------------------------ audit
async function loadAudit() {
  const entries = await api("GET", `/api/audit?plc_id=${state.current}`);
  $("#audit-body").replaceChildren(...entries.map((e) => {
    const { ts, user, action, plc_id, ...details } = e;
    return el("tr", {},
      el("td", {}, new Date(ts).toLocaleString("de-DE")),
      el("td", {}, user),
      el("td", {}, el("code", {}, action)),
      el("td", { class: "muted" }, Object.entries(details).map(([k, v]) => `${k}=${typeof v === "string" && v.length > 16 && k === "sha256" ? v.slice(0, 12) : v}`).join("  ")),
    );
  }));
}

// ------------------------------------------------------------------ tabs
function showTab(name) {
  state.tab = name;
  for (const b of document.querySelectorAll(".tabs button")) b.classList.toggle("active", b.dataset.tab === name);
  for (const t of document.querySelectorAll(".tab")) t.hidden = t.id !== `tab-${name}`;
  if (name === "variables") refreshVariables();
  if (name === "versions") loadVersions();
  if (name === "audit") loadAudit();
  if (name === "diagnostics") refreshStatus();
  if (name === "program") renderGutter();
}

// ------------------------------------------------------------------ actions
async function action(path, msg) {
  try {
    await api("POST", `/api/plcs/${state.current}/${path}`);
    toast(msg);
  } catch (e) { toast(e.message, true); }
  refreshStatus();
  loadPlcs();
}

function openNewDialog() {
  $("#new-error").hidden = true;
  $("#form-new").reset();
  $("#dlg-new").showModal();
}

async function createPlc(ev) {
  if (ev.submitter && ev.submitter.value !== "create") return;
  ev.preventDefault();
  const f = new FormData($("#form-new"));
  try {
    const plc = await api("POST", "/api/plcs", {
      name: f.get("name"),
      cycle_ms: Number(f.get("cycle_ms")),
      watchdog_ms: Number(f.get("watchdog_ms")),
      s7_enabled: f.get("s7_enabled") === "on",
      opcua_enabled: f.get("opcua_enabled") === "on",
    });
    $("#dlg-new").close();
    toast(`vPLC „${plc.name}“ angelegt`);
    await loadPlcs();
    select(plc.id);
  } catch (e) {
    $("#new-error").textContent = e.message;
    $("#new-error").hidden = false;
  }
}

async function init() {
  $("#user").value = store("vplc.user") || "";
  $("#user").addEventListener("change", () => store("vplc.user", $("#user").value.trim()));
  $("#token").addEventListener("change", () => loadPlcs().then(() => state.current && select(state.current)));
  $("#btn-new").addEventListener("click", openNewDialog);
  $("#btn-new-2").addEventListener("click", openNewDialog);
  $("#form-new").addEventListener("submit", createPlc);
  $("#btn-run").addEventListener("click", () => action("run", "RUN"));
  $("#btn-stop").addEventListener("click", () => action("stop", "STOP"));
  $("#btn-reset").addEventListener("click", () => confirm("Kaltstart: Alle Variablen werden auf ihre Initialwerte zurückgesetzt. Fortfahren?") && action("reset", "Kaltstart ausgeführt"));
  $("#btn-delete").addEventListener("click", async () => {
    if (!confirm("Diese vPLC inklusive aller Programmversionen löschen?")) return;
    try {
      await api("DELETE", `/api/plcs/${state.current}`);
      state.current = null;
      store("vplc.current", "");
      toast("vPLC gelöscht");
      loadPlcs();
    } catch (e) { toast(e.message, true); }
  });
  $("#btn-check").addEventListener("click", () => checkProgram().catch((e) => toast(e.message, true)));
  $("#btn-download").addEventListener("click", downloadProgram);
  for (const b of document.querySelectorAll(".tabs button")) b.addEventListener("click", () => showTab(b.dataset.tab));
  const src = $("#source");
  src.addEventListener("input", () => { state.dirty = true; renderGutter(); });
  src.addEventListener("scroll", () => { $("#gutter").scrollTop = src.scrollTop; });
  src.addEventListener("keydown", (ev) => {
    if (ev.key === "Tab") {
      ev.preventDefault();
      src.setRangeText("  ", src.selectionStart, src.selectionEnd, "end");
      state.dirty = true;
    } else if ((ev.ctrlKey || ev.metaKey) && ev.key === "s") {
      ev.preventDefault();
      downloadProgram();
    }
  });
  $("#var-filter").addEventListener("input", refreshVariables);
  $("#show-fb").addEventListener("change", refreshVariables);
  $("#example-select").addEventListener("change", async (ev) => {
    const name = ev.target.value;
    ev.target.value = "";
    if (!name || (state.dirty && !confirm("Editorinhalt durch Beispiel ersetzen?"))) return;
    $("#source").value = await api("GET", `/api/examples/${encodeURIComponent(name)}`, undefined, { text: true });
    state.dirty = true;
    renderErrors([]);
  });
  $("#file-open").addEventListener("change", async (ev) => {
    const file = ev.target.files[0];
    ev.target.value = "";
    if (!file || (state.dirty && !confirm("Editorinhalt durch die Datei ersetzen?"))) return;
    $("#source").value = (await file.text()).replace(/^\uFEFF/, "");  // TIA exports may start with a BOM
    state.dirty = true;
    renderErrors([]);
    checkProgram().catch(() => {});
  });
  window.addEventListener("beforeunload", (ev) => { if (state.dirty) ev.preventDefault(); });

  try {
    state.info = await api("GET", "/api/info");
    $("#token-label").hidden = !state.info.auth;
    for (const ex of state.info.examples) $("#example-select").append(el("option", { value: ex }, ex));
  } catch (e) {
    if (e.status === 401) $("#token-label").hidden = false;
  }
  await loadPlcs();
  const last = store("vplc.current");
  if (last && state.plcs.some((p) => p.id === last)) select(last);

  setInterval(() => { if (!document.hidden) { refreshStatus(); } }, 1000);
  setInterval(() => { if (!document.hidden) refreshVariables(); }, 500);
  setInterval(() => { if (!document.hidden) loadPlcs(); }, 5000);
}

init();
