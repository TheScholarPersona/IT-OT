"use strict";

/* Integration tests: real Node-RED runtime (test helper) against a real vPLC manager. */

const assert = require("assert");
const { spawn, execFileSync } = require("child_process");
const fs = require("fs");
const net = require("net");
const os = require("os");
const path = require("path");
const helper = require("node-red-node-test-helper");
const vplcNode = require("../nodes/vplc.js");
const catchNode = require("@node-red/nodes/core/common/25-catch.js");
const vplcNodes = [vplcNode, catchNode];
const { VplcClient } = require("../nodes/lib/client");

helper.init(require.resolve("node-red"));

const REPO = path.resolve(__dirname, "..", "..");
const TOKEN = "test-token";
const PROGRAM = `PROGRAM Mixer
VAR_INPUT Start : BOOL; Drehzahl : INT := 100; END_VAR
VAR_OUTPUT Motor : BOOL; Ist : INT; END_VAR
VAR CONSTANT MAX : INT := 1500; END_VAR
Motor := Start;
IF Motor THEN Ist := MIN(Drehzahl, MAX); ELSE Ist := 0; END_IF;
END_PROGRAM
`;

function freePort() {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.listen(0, "127.0.0.1", () => { const { port } = srv.address(); srv.close(() => resolve(port)); });
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

describe("node-red-contrib-it-ot-vplc", function () {
  let manager, baseUrl, dataDir, api;

  before(async function () {
    this.timeout(30000);
    const python = process.env.PYTHON || "python3";
    try { execFileSync(python, ["-c", "import vplc"], { env: { ...process.env, PYTHONPATH: path.join(REPO, "src") } }); } catch (e) {
      this.skip();
    }
    const port = await freePort();
    dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "vplc-nr-"));
    manager = spawn(python, ["-m", "vplc", "serve", "--port", String(port), "--data", dataDir], {
      env: {
        ...process.env,
        PYTHONPATH: path.join(REPO, "src"),
        VPLC_API_TOKEN: TOKEN,
        VPLC_S7_BASE_PORT: String(await freePort()),
        VPLC_OPCUA_BASE_PORT: String(await freePort()),
      },
      stdio: "ignore",
    });
    baseUrl = `http://127.0.0.1:${port}`;
    api = new VplcClient({ url: baseUrl, token: TOKEN, user: "mocha" });
    for (let i = 0; i < 100; i++) {
      try { await fetch(`${baseUrl}/api/health`); break; } catch (_) { await sleep(100); }
    }
    await api.request("POST", "/api/plcs", { name: "Mixer", source: PROGRAM, cycle_ms: 5 });
    await api.run("Mixer");
  });

  after(function () {
    if (manager) manager.kill();
    if (dataDir) fs.rmSync(dataDir, { recursive: true, force: true });
  });

  beforeEach(function (done) { helper.startServer(done); });
  afterEach(function (done) { helper.unload().then(() => helper.stopServer(done)); });

  const server = () => ({ id: "srv", type: "vplc-server", url: baseUrl, user: "node-red-test" });
  const creds = { srv: { token: TOKEN } };
  // Put every flow node on a tab; catch nodes require one.
  const load = (flow, credentials = creds) => helper.load(vplcNodes, [
    { id: "f1", type: "tab", label: "Test" },
    ...flow.map((n, i) => (n.type === "vplc-server" ? n : { x: 100, y: 40 * (i + 1), ...n, z: "f1" })),
  ], credentials);

  it("registers all node types", async function () {
    await load([server()]);
    const s = helper.getNode("srv");
    assert.ok(s && s.client);
  });

  it("vplc out writes a single variable and vplc in reports the change", async function () {
    await api.writeMany("Mixer", { Start: false, Drehzahl: 100 });
    const flow = [
      server(),
      { id: "in", type: "vplc in", server: "srv", plc: "Mixer", variables: "Ist, Motor", output: "each", interval: 20, initial: true, wires: [["sink"]] },
      { id: "sink", type: "helper" },
      { id: "out", type: "vplc out", server: "srv", plc: "Mixer", variable: "" },
    ];
    await load(flow);
    const received = [];
    const sink = helper.getNode("sink");
    const gotIst = new Promise((resolve) => {
      sink.on("input", (msg) => {
        received.push(msg);
        if (msg.topic === "Ist" && msg.payload === 800) resolve(msg);
      });
    });
    await sleep(300);
    assert.ok(received.some((m) => m.initial && m.topic === "Ist" && m.payload === 0), "initial snapshot");
    helper.getNode("out").receive({ topic: "Drehzahl", payload: 800 });
    helper.getNode("out").receive({ topic: "Start", payload: true });
    const msg = await gotIst;
    assert.strictEqual(msg.plc, "Mixer");
    assert.strictEqual(msg.mode, "RUN");
    assert.strictEqual(msg.initial, false);
    const audit = await api.request("GET", "/api/audit?plc_id=Mixer");
    assert.strictEqual(audit[0].user, "node-red-test");
  });

  it("vplc out writes an object atomically and reports errors to catch", async function () {
    const flow = [
      server(),
      { id: "out", type: "vplc out", server: "srv", plc: "Mixer" },
      { id: "catch", type: "catch", scope: ["out"], wires: [["errs"]] },
      { id: "errs", type: "helper" },
    ];
    await load(flow);
    const caught = new Promise((resolve) => helper.getNode("errs").on("input", resolve));
    helper.getNode("out").receive({ payload: { Drehzahl: 1234, Gibtsnicht: 1 } });
    const err = await caught;
    assert.match(err.error.message, /Gibtsnicht/);
    const values = await api.read("Mixer");
    assert.notStrictEqual(values.Drehzahl, 1234, "nothing written on error");
    helper.getNode("out").receive({ payload: { Drehzahl: 1234, Start: true } });
    await sleep(200);
    assert.strictEqual((await api.read("Mixer")).Drehzahl, 1234);
  });

  it("vplc in with output 'all' sends the full value object", async function () {
    const flow = [
      server(),
      { id: "in", type: "vplc in", server: "srv", plc: "Mixer", variables: "", output: "all", interval: 20, initial: true, wires: [["sink"]] },
      { id: "sink", type: "helper" },
    ];
    await load(flow);
    const msg = await new Promise((resolve) => helper.getNode("sink").on("input", resolve));
    assert.deepStrictEqual(Object.keys(msg.payload).sort(), ["Drehzahl", "Ist", "MAX", "Motor", "Start"]);
  });

  it("vplc control: stop, run, read, download with compile errors, versions", async function () {
    const flow = [
      server(),
      { id: "ctl", type: "vplc control", server: "srv", plc: "Mixer", action: "msg", wires: [["sink"]] },
      { id: "sink", type: "helper" },
      { id: "catch", type: "catch", scope: ["ctl"], wires: [["errs"]] },
      { id: "errs", type: "helper" },
    ];
    await load(flow);
    const ctl = helper.getNode("ctl");
    const call = (msg) => new Promise((resolve) => {
      helper.getNode("sink").once("input", resolve);
      ctl.receive(msg);
    });

    assert.strictEqual((await call({ action: "stop" })).payload.mode, "STOP");
    assert.strictEqual((await call({ action: "run" })).payload.mode, "RUN");
    assert.ok("Drehzahl" in (await call({ action: "read" })).payload);

    const caught = new Promise((resolve) => helper.getNode("errs").once("input", resolve));
    ctl.receive({ action: "download", payload: "PROGRAM X\nfoo := 1;\nEND_PROGRAM" });
    const err = await caught;
    assert.strictEqual(err.errors[0].line, 2);

    const res = await call({ action: "download", payload: PROGRAM.replace("MIN(Drehzahl, MAX)", "Drehzahl"), comment: "ohne Begrenzung" });
    assert.ok(res.payload.version.version >= 2);
    const versions = (await call({ action: "versions" })).payload;
    assert.strictEqual(versions[0].comment, "ohne Begrenzung");
    assert.strictEqual(versions[0].author, "node-red-test");
  });

  it("shows a disconnected status for a wrong token instead of crashing", async function () {
    const flow = [
      server(),
      { id: "in", type: "vplc in", server: "srv", plc: "Mixer", interval: 50, wires: [[]] },
    ];
    await load(flow, { srv: { token: "falsch" } });
    const node = helper.getNode("in");
    const status = await new Promise((resolve) => {
      node.on("call:status", (call) => {
        const s = call.args[0];
        if (s.fill === "red") resolve(s);
      });
    });
    assert.match(status.text, /getrennt|401|Token/);
  });
});
