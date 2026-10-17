import type { Selection } from "./api";

export const POINTER = "content-strategy.selection.v1";
export const RECEIPTS = "content-strategy.receipts.v1";
export type SavedReceipt = { selection: Selection; key: string };

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function selection(value: unknown): Selection | null {
  if (!object(value) || typeof value.dataset_id !== "string" ||
      value.dataset_id.length !== 43 || !/^s9-dataset-[0-9a-f]{32}$/.test(value.dataset_id) ||
      typeof value.snapshot_id !== "string" || value.snapshot_id.length !== 64 ||
      !/^[0-9a-f]{64}$/.test(value.snapshot_id)) return null;
  return { dataset_id: value.dataset_id, snapshot_id: value.snapshot_id };
}

function read(key: string): unknown {
  // Browser storage may be corrupt, disabled, or unavailable in a static render.
  try { return JSON.parse(localStorage.getItem(key) || "null") as unknown; }
  catch { return null; }
}

export function savedSelection(): Selection | null {
  return selection(read(POINTER));
}

function write(key: string, value: unknown): boolean {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; }
  catch { return false; }
}

export function saveSelection(value: Selection): boolean {
  return write(POINTER, value);
}

export function saveReceipts(value: SavedReceipt[]): boolean {
  return write(RECEIPTS, value);
}

function distinctReceipts(rows: SavedReceipt[]): SavedReceipt[] {
  const seen = new Set<string>();
  return rows.filter(row => {
    const identity = JSON.stringify([row.selection.dataset_id, row.selection.snapshot_id, row.key]);
    if (seen.has(identity)) return false;
    seen.add(identity);
    return true;
  }).slice(0, 20);
}

export function rememberReceipt(selected: Selection, key: string, current: SavedReceipt[],
  unpersisted: SavedReceipt[] = []) {
  const pending = distinctReceipts([{ selection: selected, key }, ...unpersisted]);
  const receipts = distinctReceipts([...pending, ...savedReceipts(), ...current]);
  const persisted = saveReceipts(receipts);
  return { receipts, persisted, unpersisted: persisted ? [] : pending };
}

export function savedReceipts(): SavedReceipt[] {
  const value = read(RECEIPTS);
  if (!Array.isArray(value)) return [];
  const receipts: SavedReceipt[] = [];
  const seen = new Set<string>();
  for (const row of value) {
    if (!object(row) || typeof row.key !== "string" || row.key.length === 0 ||
        row.key.length > 256 || row.key.trim() !== row.key || /[\x00-\x1f]/.test(row.key)) continue;
    const selected = selection(row.selection);
    if (!selected) continue;
    const identity = JSON.stringify([selected.dataset_id, selected.snapshot_id, row.key]);
    if (seen.has(identity)) continue;
    seen.add(identity);
    // Stored fields are lookup pointers, never approval or receipt authority.
    receipts.push({ selection: selected, key: row.key });
    if (receipts.length === 20) break;
  }
  return receipts;
}
