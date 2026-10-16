import assert from "node:assert/strict";
import test from "node:test";
import { POINTER, RECEIPTS, savedReceipts, savedSelection } from "../../web/saved-workspace.ts";

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
