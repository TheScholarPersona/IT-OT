"use strict";

const { VplcClient } = require("./lib/client");

const ACTIONS = ["run", "stop", "reset", "status", "read", "download", "check", "versions", "activate"];

module.exports = function (RED) {
  // ------------------------------------------------------------------ config
  function VplcServerNode(config) {
    RED.nodes.createNode(this, config);
    this.url = config.url || "http://localhost:8080";
    this.user = config.user || "node-red";
    // Fallback for container deployments: token from the environment
    const token = (this.credentials && this.credentials.token) || process.env.VPLC_API_TOKEN || "";
    this.client = new VplcClient({ url: this.url, token, user: this.user });
  }
  RED.nodes.registerType("vplc-server", VplcServerNode, {
    credentials: { token: { type: "password" } },
  });

  function serverOf(node, config) {
    const server = RED.nodes.getNode(config.server);
    if (!server) {
      node.status({ fill: "red", shape: "ring", text: "kein vPLC-Manager konfiguriert" });
      return null;
    }
    return server;
  }

  function modeStatus(node, mode, extra) {
    const running = mode === "RUN";
    node.status({ fill: running ? "green" : "yellow", shape: "dot", text: `${mode}${extra ? " · " + extra : ""}` });
  }

  function splitList(text) {
    return String(text || "").split(/[,;\s]+/).map((s) => s.trim()).filter(Boolean);
  }

  // ------------------------------------------------------------------ vplc in
  function VplcInNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    const server = serverOf(node, config);
    if (!server) return;
    const plc = config.plc;
    const output = config.output || "each"; // each | object | all
    const sendInitial = config.initial !== false;
    const intervalMs = Math.max(20, Number(config.interval) || 100);
    let values = {};
    let status = {};

    const emit = (changed, initial) => {
      const base = { plc: status.name || plc, mode: status.mode, initial };
      if (output === "each") {
        const msgs = Object.entries(changed).map(([name, value]) => ({ ...base, topic: name, payload: value }));
        msgs.forEach((m) => node.send(m));
      } else if (output === "object") {
        node.send({ ...base, topic: status.name || plc, payload: changed });
      } else {
        node.send({ ...base, topic: status.name || plc, payload: { ...values }, changed: Object.keys(changed) });
      }
    };

    node.status({ fill: "grey", shape: "ring", text: "verbinde …" });
    const sub = server.client.subscribe(plc, { intervalMs, variables: splitList(config.variables) }, {
      onState(state, detail) {
        if (state === "connected") return; // the snapshot sets the status
        const fill = state === "connecting" ? "grey" : "red";
        node.status({ fill, shape: "ring", text: state === "connecting" ? "verbinde …" : `getrennt${detail ? ": " + detail : ""}` });
        if (state === "error" && detail) node.debug(`vPLC-Stream: ${detail}`);
      },
      onMessage(msg) {
        if (msg.type === "snapshot") {
          status = msg.status;
          values = msg.values;
          if (msg.unknown && msg.unknown.length) {
            node.warn(`Unbekannte Variablen in vPLC „${status.name}“: ${msg.unknown.join(", ")}`);
          }
          modeStatus(node, status.mode, status.program ? `${status.program} v${status.program_version}` : "kein Programm");
          if (sendInitial && Object.keys(values).length) emit(values, true);
        } else if (msg.type === "changes") {
          Object.assign(values, msg.values);
          emit(msg.values, false);
        } else if (msg.type === "status") {
          status = msg.status;
          modeStatus(node, status.mode, status.last_error ? status.last_error.message : null);
        }
      },
    });

    node.on("close", (done) => {
      sub.close();
      done();
    });
  }
  RED.nodes.registerType("vplc in", VplcInNode);

  // ------------------------------------------------------------------ vplc out
  function VplcOutNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    const server = serverOf(node, config);
    if (!server) return;

    node.on("input", async (msg, send, done) => {
      const plc = config.plc || msg.plc;
      const variable = config.variable || (typeof msg.topic === "string" ? msg.topic : "");
      try {
        let written;
        if (variable) {
          if (msg.payload === undefined || msg.payload === null || typeof msg.payload === "object") {
            throw new Error(`msg.payload muss ein Einzelwert sein, um „${variable}“ zu schreiben`);
          }
          const r = await server.client.write(plc, variable, msg.payload);
          written = { [r.name]: r.value };
        } else if (msg.payload && typeof msg.payload === "object" && !Array.isArray(msg.payload)) {
          written = (await server.client.writeMany(plc, msg.payload)).values;
        } else {
          throw new Error("Keine Variable: im Node konfigurieren, msg.topic setzen oder msg.payload als Objekt {Name: Wert} senden");
        }
        const names = Object.keys(written);
        node.status({ fill: "green", shape: "dot", text: `${names.length === 1 ? names[0] + " = " + written[names[0]] : names.length + " Variablen"} geschrieben` });
        done();
      } catch (err) {
        node.status({ fill: "red", shape: "ring", text: err.message.slice(0, 60) });
        done(err);
      }
    });
  }
  RED.nodes.registerType("vplc out", VplcOutNode);

  // ------------------------------------------------------------------ vplc control
  function VplcControlNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    const server = serverOf(node, config);
    if (!server) return;

    node.on("input", async (msg, send, done) => {
      const plc = config.plc || msg.plc;
      const action = String(config.action === "msg" || !config.action ? (msg.action || msg.topic || "") : config.action).toLowerCase();
      const c = server.client;
      try {
        if (!ACTIONS.includes(action)) {
          throw new Error(`Unbekannte Aktion „${action}“ (erlaubt: ${ACTIONS.join(", ")})`);
        }
        let result;
        switch (action) {
          case "run": result = await c.run(plc); break;
          case "stop": result = await c.stop(plc); break;
          case "reset": result = await c.reset(plc); break;
          case "status": result = await c.status(plc); break;
          case "read": result = await c.read(plc); break;
          case "versions": result = await c.versions(plc); break;
          case "activate": result = await c.activate(plc, msg.payload); break;
          case "check":
            if (typeof msg.payload !== "string") throw new Error("msg.payload muss den Programmtext enthalten");
            result = await c.check(msg.payload);
            break;
          case "download":
            if (typeof msg.payload !== "string") throw new Error("msg.payload muss den Programmtext enthalten");
            result = await c.download(plc, msg.payload, msg.comment || "", msg.warm !== false);
            break;
        }
        if (result && result.mode) modeStatus(node, result.mode, action);
        else node.status({ fill: "green", shape: "dot", text: `${action} ok` });
        msg.payload = result;
        msg.action = action;
        send(msg);
        done();
      } catch (err) {
        node.status({ fill: "red", shape: "ring", text: `${action}: ${err.message}`.slice(0, 60) });
        if (err.errors) msg.errors = err.errors;
        done(err);
      }
    });
  }
  RED.nodes.registerType("vplc control", VplcControlNode);

  // ------------------------------------------------------------------ editor helper
  // Lets the editor offer a list of PLCs from the configured manager.
  RED.httpAdmin.get("/vplc/plcs/:server", RED.auth.needsPermission("vplc-server.read"), async (req, res) => {
    const server = RED.nodes.getNode(req.params.server);
    if (!server) return res.status(404).json({ error: "Manager-Konfiguration noch nicht bereitgestellt (Deploy)" });
    try {
      const plcs = await server.client.listPlcs();
      res.json(plcs.map((p) => ({ id: p.id, name: p.name, mode: p.mode, program: p.program })));
    } catch (err) {
      res.status(502).json({ error: err.message });
    }
  });
};
