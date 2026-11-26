"use strict";

const WebSocket = require("ws");

/** Error returned by the vPLC manager (HTTP status + details). */
class VplcError extends Error {
  constructor(message, status, errors) {
    super(message);
    this.name = "VplcError";
    this.status = status;
    this.errors = errors;
  }
}

/** Minimal client for the vPLC manager REST API and live stream. */
class VplcClient {
  constructor({ url, token, user, timeoutMs = 10000 }) {
    this.baseUrl = String(url || "http://localhost:8080").replace(/\/+$/, "");
    this.token = token || "";
    this.user = user || "node-red";
    this.timeoutMs = timeoutMs;
  }

  headers(extra = {}) {
    const h = { "X-User": this.user, ...extra };
    if (this.token) h.Authorization = `Bearer ${this.token}`;
    return h;
  }

  plcPath(plc) {
    if (!plc) throw new VplcError("Keine vPLC angegeben (Name oder ID)", 400);
    return `/api/plcs/${encodeURIComponent(plc)}`;
  }

  async request(method, path, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    let res;
    try {
      res = await fetch(this.baseUrl + path, {
        method,
        headers: this.headers(body === undefined ? {} : { "Content-Type": "application/json" }),
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (err) {
      const reason = err.name === "AbortError" ? "Zeitüberschreitung" : (err.cause && err.cause.code) || err.message;
      throw new VplcError(`vPLC-Manager nicht erreichbar (${this.baseUrl}): ${reason}`, 0);
    } finally {
      clearTimeout(timer);
    }
    if (res.status === 204) return null;
    const text = await res.text();
    let data = text;
    if ((res.headers.get("content-type") || "").includes("application/json")) {
      try { data = JSON.parse(text); } catch (_) { /* keep text */ }
    }
    if (!res.ok) {
      const detail = data && typeof data === "object" && typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`;
      throw new VplcError(detail, res.status, data && data.errors);
    }
    return data;
  }

  // ------------------------------------------------------------------ API
  status(plc) { return this.request("GET", this.plcPath(plc)); }
  run(plc) { return this.request("POST", `${this.plcPath(plc)}/run`); }
  stop(plc) { return this.request("POST", `${this.plcPath(plc)}/stop`); }
  reset(plc) { return this.request("POST", `${this.plcPath(plc)}/reset`); }
  versions(plc) { return this.request("GET", `${this.plcPath(plc)}/versions`); }
  activate(plc, version) { return this.request("POST", `${this.plcPath(plc)}/versions/${encodeURIComponent(version)}/activate`); }
  check(source) { return this.request("POST", "/api/check", { source }); }
  listPlcs() { return this.request("GET", "/api/plcs"); }

  download(plc, source, comment = "", warm = true) {
    return this.request("PUT", `${this.plcPath(plc)}/program`, { source, comment, warm });
  }

  async read(plc) {
    const vars = await this.request("GET", `${this.plcPath(plc)}/variables`);
    const out = {};
    for (const v of vars) if (!v.name.includes(".")) out[v.name] = v.value;
    return out;
  }

  write(plc, name, value) {
    return this.request("PUT", `${this.plcPath(plc)}/variables/${encodeURIComponent(name)}`, { value });
  }

  writeMany(plc, values) {
    return this.request("PUT", `${this.plcPath(plc)}/variables`, { values });
  }

  /**
   * Open a live stream with automatic reconnect.
   * handlers: onMessage(msg), onState(state, detail) with state in
   *           "connecting" | "connected" | "disconnected" | "error"
   * Returns an object with close().
   */
  subscribe(plc, { intervalMs = 100, variables = [] } = {}, handlers = {}) {
    const params = new URLSearchParams({ interval_ms: String(intervalMs) });
    if (variables.length) params.set("variables", variables.join(","));
    const wsUrl = this.baseUrl.replace(/^http/i, "ws") + `${this.plcPath(plc)}/stream?${params}`;
    const onMessage = handlers.onMessage || (() => {});
    const onState = handlers.onState || (() => {});
    let ws = null;
    let closed = false;
    let retryTimer = null;
    let delay = 1000;

    const connect = () => {
      if (closed) return;
      onState("connecting");
      ws = new WebSocket(wsUrl, { headers: this.headers() });
      ws.on("open", () => { delay = 1000; onState("connected"); });
      ws.on("message", (data) => {
        let msg;
        try { msg = JSON.parse(data.toString()); } catch (_) { return; }
        onMessage(msg);
      });
      ws.on("unexpected-response", (_req, res) => {
        onState("error", `HTTP ${res.statusCode}`);
      });
      ws.on("error", (err) => {
        onState("error", (err.cause && err.cause.code) || err.code || err.message);
      });
      ws.on("close", (code, reason) => {
        ws = null;
        if (closed) return;
        const text = reason && reason.toString();
        // 4401 = token, 4404 = unknown PLC: retry slowly, the user has to fix the config
        const permanent = code === 4401 || code === 4404;
        onState(permanent ? "error" : "disconnected", text || (code ? `Code ${code}` : ""));
        const wait = permanent ? 10000 : delay;
        delay = Math.min(delay * 2, 30000);
        retryTimer = setTimeout(connect, wait);
      });
    };
    connect();

    return {
      close() {
        closed = true;
        clearTimeout(retryTimer);
        if (ws) {
          try { ws.close(1000); } catch (_) { /* ignore */ }
          ws.terminate && setTimeout(() => ws && ws.terminate(), 1000).unref();
        }
      },
    };
  }
}

module.exports = { VplcClient, VplcError };
