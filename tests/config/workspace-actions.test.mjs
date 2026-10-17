import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdir, mkdtemp, writeFile, rm, rmdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "vite";

// Exercise the real App and LocalApi action closures with interpreted hooks and
// canned HTTP. This checks wiring/state transitions, not React lifecycle or a browser.
const root = fileURLToPath(new URL("../..", import.meta.url));
const appPath = resolve(root, "web/app.tsx");
const scratchBase = resolve(process.env.CSA_ACTION_TEST_TMP || tmpdir());
await mkdir(scratchBase, { recursive: true });
const scratch = await mkdtemp(join(scratchBase, "csa-action-"));
const bundlePath = join(scratch, "app.mjs");
after(async () => {
  assert.equal(dirname(scratch), scratchBase);
  await rm(bundlePath, { force: true });
  await rmdir(scratch);
});
const hookSource = `
export function useState(initial) {
  const h=globalThis.__csaActionHooks,i=h.cursor++;
  if(!(i in h.state)) h.state[i]=typeof initial==='function'?initial():initial;
  return [h.state[i],v=>h.state[i]=typeof v==='function'?v(h.state[i]):v];
}
export function useRef(initial) {
  const h=globalThis.__csaActionHooks,i=h.cursor++;
  return h.refs[i]??=({current:initial});
}
export function useEffect(effect) {
  const h=globalThis.__csaActionHooks,i=h.cursor++;
  if(!h.effectSeen.has(i)){h.effectSeen.add(i);h.effects.push(effect);}
}`;
const result = await build({
  configFile: false, root, logLevel: "silent", ssr: { noExternal: true },
  plugins: [{
    name: "workspace-action-test", enforce: "pre",
    resolveId(id) { if (id === "virtual:workspace-action-hooks") return "\0workspace-action-hooks"; },
    load(id) { if (id === "\0workspace-action-hooks") return hookSource; },
    transform(code, id) {
      if (resolve(id) !== appPath) return;
      const bootstrap = code.lastIndexOf("createRoot(document");
      assert.ok(bootstrap > 0, "App bootstrap boundary must be explicit");
      return code.slice(0, bootstrap).replace('from "react"', 'from "virtual:workspace-action-hooks"') + "\nexport { App };\n";
    },
  }],
  build: { ssr: appPath, write: false, minify: false,
    rolldownOptions: { output: { format: "es", codeSplitting: false } } },
});
const output = (Array.isArray(result) ? result[0] : result).output;
const chunk = output.find(item => item.type === "chunk" && item.isEntry);
assert.ok(chunk, "actual App bundle must exist");
await writeFile(bundlePath, chunk.code);
const { App } = await import(pathToFileURL(bundlePath).href);

const selection = { dataset_id: "s9-dataset-" + "a".repeat(32), snapshot_id: "b".repeat(64) };
const version = { schema_version: 1, item_id: "synthetic-draft", revision: 1,
  content_hash: "c".repeat(64), evidence_generation: selection.snapshot_id };
const receiptKey = "content-strategy.receipts.v1";
function nodes(node) {
  if (!node || typeof node !== "object") return [];
  return Array.isArray(node) ? node.flatMap(nodes) : [node, ...nodes(node.props?.children)];
}
function text(node) {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node !== "object") return String(node);
  return Array.isArray(node) ? node.map(text).join("") : text(node.props?.children);
}

async function workspace(t, { denyStorage = false, refuseExport = false, state = "approved" } = {}) {
  const hooks = { state: [], refs: [], cursor: 0, effects: [], effectSeen: new Set() };
  const previousHooks = Object.getOwnPropertyDescriptor(globalThis, "__csaActionHooks");
  Object.defineProperty(globalThis, "__csaActionHooks", { configurable: true, value: hooks });
  t.after(() => {
    if (previousHooks) Object.defineProperty(globalThis, "__csaActionHooks", previousHooks);
    else delete globalThis.__csaActionHooks;
  });
  const values = { "content-strategy.selection.v1": JSON.stringify(selection) };
  const storageDescriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem(key) { return values[key] ?? null; },
    setItem(key, value) {
      if (denyStorage) throw new DOMException("Synthetic denied write", "QuotaExceededError");
      values[key] = value;
    },
  } });
  t.after(() => {
    if (storageDescriptor) Object.defineProperty(globalThis, "localStorage", storageDescriptor);
    else delete globalThis.localStorage;
  });
  let currentState = state, sequence = 1, committed = null;
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const body = options?.body ? JSON.parse(options.body) : null;
    calls.push({ url, body });
    let response, status = 200;
    if (url === "/api/session") response = { csrf: "synthetic", execution_origin: "authored_synthetic_mock" };
    else if (url === "/api/report") response = { selection, rows: [], platforms: [] };
    else if (url === "/api/history") response = { rows: [{ version, kind: "draft", parent_id: "parent",
      parent_revision: 1, state: currentState }], sequence };
    else if (url === "/api/activate") response = { sequence };
    else if (url === "/api/preview") response = { version, body: "Synthetic checked draft", editable_text: "Synthetic draft",
      scope: "x", kind: "draft", sequence, evidence: [] };
    else if (url === "/api/export") {
      if (refuseExport || currentState !== "approved") { status = 409; response = { code: "current_approval_required" }; }
      else {
        currentState = "exported"; sequence++;
        committed = { receipt: { export_id: "synthetic-receipt", idempotency_key: body.idempotency_key,
          item_versions: [version] }, historical_replay: false, markdown_base64: "", csv_base64: "" };
        response = committed;
      }
    } else if (url === "/api/receipt") {
      assert.equal(body.idempotency_key, committed.receipt.idempotency_key);
      response = { ...committed, historical_replay: true };
    } else assert.fail("Unexpected request " + url);
    return new Response(JSON.stringify(response), { status, headers: { "Content-Type": "application/json" } });
  });
  function render() { hooks.cursor = 0; return App(); }
  async function settle() { for (let i = 0; i < 12; i++) await new Promise(resolve => setImmediate(resolve)); }
  function button(label) { return nodes(render()).find(node => node.type === "button" && text(node).trim().startsWith(label)); }
  async function click(label) {
    const target = button(label);
    assert.ok(target, label);
    assert.equal(Boolean(target.props.disabled), false, label + " must be enabled");
    target.props.onClick(); await settle();
  }
  const keys = () => nodes(render()).filter(node => node.props?.className === "receipt-link").map(text);
  render(); for (const effect of hooks.effects) effect(); await settle();
  await click("Use this snapshot"); await click("Draft 1");
  return { render, button, click, settle, calls, keys, values };
}

for (const denyStorage of [false, true]) test(`exported draft cannot create another request/key; recovery survives (storage denied=${denyStorage})`, async t => {
  // what_bug_this_catches: exported was treated as current approval by the UI,
  // creating a misleading NEW export action and lookup key before server refusal.
  const app = await workspace(t, { denyStorage });
  await app.click("Export approved draft");
  assert.equal(app.calls.filter(call => call.url === "/api/export").length, 1);
  assert.match(text(app.render()), /Approved bytes committed/);
  const keys = app.keys();
  assert.equal(keys.length, 1);
  if (denyStorage) assert.match(text(app.render()), /Recovery pointers could not be saved/);
  else assert.equal(JSON.parse(app.values[receiptKey]).length, 1);
  await app.click("Draft 1");
  const exportedAction = app.button("Export approved draft");
  assert.equal(exportedAction.props.disabled, true, "exported is historical, not current approval");
  // Also exercise the actual callback defensively; disabled DOM behavior is not
  // supplied by this hook interpreter, and the action must not allocate a key.
  exportedAction.props.onClick(); await app.settle();
  assert.equal(app.calls.filter(call => call.url === "/api/export").length, 1);
  assert.deepEqual(app.keys(), keys);
  await app.click(keys[0].replace("Recover →", ""));
  assert.match(text(app.render()), /Historical receipt recovered/);
  assert.equal(nodes(app.render()).filter(node => node.type === "a" && node.props.href?.startsWith("/api/download/")).length, 2);
});

test("current approved action still preserves server refusal and pending recovery key", async t => {
  // what_bug_this_catches: tightening the NEW-action guard must not hide stale
  // server authority failures or discard the lookup key of an interrupted export.
  const app = await workspace(t, { refuseExport: true, denyStorage: true });
  await app.click("Export approved draft");
  assert.equal(app.calls.filter(call => call.url === "/api/export").length, 1);
  assert.match(text(app.render()), /current approval required/);
  assert.ok(nodes(app.render()).some(node => node.props?.role === "alert"));
  assert.equal(app.keys().length, 1);
});
