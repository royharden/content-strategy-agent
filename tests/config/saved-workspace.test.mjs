import assert from "node:assert/strict";
import test from "node:test";
import { POINTER, RECEIPTS, rememberReceipt, saveReceipts, saveSelection, savedReceipts, savedSelection } from "../../web/saved-workspace.ts";

const selection = { dataset_id: "s9-dataset-" + "a".repeat(32), snapshot_id: "b".repeat(64) };
const receipt = { selection, key: "web-synthetic-receipt" };

function storage(t, values) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem(key) { return values[key] ?? null; },
    setItem() { assert.fail("loading pointers must not rewrite storage"); },
  } });
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, "localStorage", previous);
    else delete globalThis.localStorage;
  });
}

test("restart drops malformed rows while preserving a valid receipt lookup", (t) => {
  // what_bug_this_catches: [null] used to reach App rendering and crash on saved.key.
  storage(t, { [RECEIPTS]: JSON.stringify([null, 1, "pointer", [], {},
    { key: "lookup" }, { selection }, { selection: null, key: "lookup" }, receipt]) });
  assert.deepEqual(savedReceipts(), [receipt]);
});

test("corrupt and non-array receipt JSON cannot prevent the workspace from opening", (t) => {
  // what_bug_this_catches: valid JSON is not necessarily the expected list of pointers.
  const values = {};
  storage(t, values);
  for (const raw of ["{", "null", "{}", "3", '"pointer"', "true", "[]"]) {
    values[RECEIPTS] = raw;
    assert.deepEqual(savedReceipts(), [], raw);
  }
});

test("invalid selections and keys do not become receipt requests", (t) => {
  // what_bug_this_catches: unchecked casts forwarded malformed persisted fields to recovery.
  const invalid = [null, {}, { ...selection, dataset_id: "other" },
    { ...selection, dataset_id: selection.dataset_id + "\n" },
    { ...selection, snapshot_id: "B".repeat(64) },
    { ...selection, snapshot_id: selection.snapshot_id + "\n" },
    { ...selection, snapshot_id: 1 }];
  const rows = invalid.map(value => ({ selection: value, key: "lookup" }));
  rows.push(...[null, 2, "", " space", "space ", "a\nb", "\0", "x".repeat(257)]
    .map(key => ({ selection, key })));
  storage(t, { [RECEIPTS]: JSON.stringify([...rows, receipt]) });
  assert.deepEqual(savedReceipts(), [receipt]);
});

test("persisted approval-looking fields are discarded, leaving only lookup identity", (t) => {
  // what_bug_this_catches: browser persistence must never supply server decision authority.
  storage(t, { [RECEIPTS]: JSON.stringify([{ ...receipt, state: "approved", approve: true,
    selection: { ...selection, actor: "forged", schema_version: 1 } }]) });
  assert.deepEqual(savedReceipts(), [receipt]);
});

test("receipt cap counts valid distinct identities without losing later valid pointers", (t) => {
  // what_bug_this_catches: corrupt/duplicate prefixes hid recoverable receipt entries.
  const rows = Array.from({ length: 23 }, (_, i) => ({ selection, key: `receipt-${i}` }));
  const secondSelection = { ...selection, snapshot_id: "c".repeat(64) };
  storage(t, { [RECEIPTS]: JSON.stringify([
    ...Array(30).fill(null), rows[0], rows[0], { selection: secondSelection, key: rows[0].key }, ...rows.slice(1),
  ]) });
  assert.deepEqual(savedReceipts(), [rows[0], { selection: secondSelection, key: rows[0].key }, ...rows.slice(1, 19)]);
});

test("saved snapshot selection is validated and projected before restart", (t) => {
  // what_bug_this_catches: malformed JSON selection used to be sent blindly to report.
  const values = { [POINTER]: JSON.stringify({ ...selection, approve: true }) };
  storage(t, values);
  assert.deepEqual(savedSelection(), selection);
  for (const raw of ["{", "null", "[]", "{}", JSON.stringify({ ...selection, dataset_id: "wrong" })]) {
    values[POINTER] = raw;
    assert.equal(savedSelection(), null, raw);
  }
});

test("denied storage access leaves empty optional pointers and performs no writes", (t) => {
  // what_bug_this_catches: a browser storage SecurityError blocked the startup handshake.
  storage(t, {});
  Object.defineProperty(globalThis, "localStorage", { configurable: true,
    get() { throw new DOMException("Storage unavailable", "SecurityError"); },
  });
  assert.deepEqual(savedReceipts(), []);
  assert.equal(savedSelection(), null);
});

test("denied or full browser storage reports unsaved pointers without throwing", (t) => {
  // what_bug_this_catches: a storage write blocked an already retained import or prevented export dispatch.
  storage(t, {});
  for (const name of ["SecurityError", "QuotaExceededError"]) {
    Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
      setItem() { throw new DOMException("Cannot persist", name); },
    } });
    assert.equal(saveSelection(selection), false, name);
    assert.equal(saveReceipts([receipt]), false, name);
  }
  Object.defineProperty(globalThis, "localStorage", { configurable: true,
    get() { throw new DOMException("Storage unavailable", "SecurityError"); },
  });
  assert.equal(saveSelection(selection), false);
  assert.equal(saveReceipts([receipt]), false);
});

test("successful pointer writes remain recoverable after a new read", (t) => {
  // what_bug_this_catches: best-effort persistence must still preserve successful restart lookups.
  const values = {};
  storage(t, values);
  globalThis.localStorage.setItem = (key, value) => { values[key] = value; };
  assert.equal(saveSelection(selection), true);
  assert.equal(saveReceipts([receipt]), true);
  assert.deepEqual(savedSelection(), selection);
  assert.deepEqual(savedReceipts(), [receipt]);
});

test("remembering a receipt merges another tab's saved pointers with this tab's memory", (t) => {
  // what_bug_this_catches: a state-only fallback overwrote pointers saved by another tab after startup.
  const external = { selection, key: "other-tab" };
  const local = { selection, key: "this-tab" };
  const values = { [RECEIPTS]: JSON.stringify([external, local]) };
  storage(t, values);
  globalThis.localStorage.setItem = (key, value) => { values[key] = value; };
  const result = rememberReceipt(selection, receipt.key, [local]);
  assert.equal(result.persisted, true);
  assert.deepEqual(result.receipts, [receipt, external, local]);
  assert.deepEqual(savedReceipts(), result.receipts);
});

test("failed writes preserve distinct in-memory receipt identities up to the restart cap", (t) => {
  // what_bug_this_catches: a second export lost the first unsaved key, or collapsed another snapshot's same key.
  storage(t, {});
  globalThis.localStorage.setItem = () => { throw new DOMException("Full", "QuotaExceededError"); };
  const first = rememberReceipt(selection, receipt.key, []);
  assert.equal(first.persisted, false);
  const other = { ...selection, snapshot_id: "c".repeat(64) };
  const second = rememberReceipt(other, receipt.key, first.receipts, first.unpersisted);
  assert.equal(second.persisted, false);
  assert.deepEqual(second.receipts, [{ selection: other, key: receipt.key }, receipt]);
  const many = Array.from({ length: 30 }, (_, i) => ({ selection, key: `lookup-${i}` }));
  assert.deepEqual(rememberReceipt(selection, receipt.key, [receipt, ...many]).receipts,
    [receipt, ...many.slice(0, 19)]);
});

test("a full stored history cannot evict recent unsaved keys before storage recovers", (t) => {
  // what_bug_this_catches: twenty old stored rows evicted the previous unsaved export on the next failed write.
  const old = Array.from({ length: 20 }, (_, i) => ({ selection, key: `old-${i}` }));
  const values = { [RECEIPTS]: JSON.stringify(old) };
  storage(t, values);
  globalThis.localStorage.setItem = () => { throw new DOMException("Full", "QuotaExceededError"); };
  const first = rememberReceipt(selection, "new-1", old);
  const second = rememberReceipt(selection, "new-2", first.receipts, first.unpersisted);
  assert.equal(second.persisted, false);
  assert.deepEqual(second.receipts, [
    { selection, key: "new-2" }, { selection, key: "new-1" }, ...old.slice(0, 18),
  ]);
  assert.deepEqual(second.unpersisted, second.receipts.slice(0, 2));
  globalThis.localStorage.setItem = (key, value) => { values[key] = value; };
  const recovered = rememberReceipt(selection, "new-3", second.receipts, second.unpersisted);
  assert.equal(recovered.persisted, true);
  assert.deepEqual(recovered.unpersisted, []);
  assert.deepEqual(savedReceipts(), recovered.receipts);
  assert.deepEqual(recovered.receipts.slice(0, 3).map(row => row.key), ["new-3", "new-2", "new-1"]);
});
