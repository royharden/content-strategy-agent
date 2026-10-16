export type Selection = { dataset_id: string; snapshot_id: string };
export type Version = {
  schema_version: number; item_id: string; revision: number;
  content_hash: string; evidence_generation: string;
};
export type Metric = {
  metric_id: string; definition: string; value: string | null; unit: string;
  sample_size: number; scope: string; computed_by: string;
  status: "ok" | "unavailable" | "insufficient_data";
};
export type Report = {
  selection: Selection; rows: { metric: Metric; family: string }[];
  platforms: { platform: string; rows: number }[];
};
export type Item = {
  version: Version; kind: "recommendation" | "draft";
  parent_id: string | null; parent_revision: number | null;
  state: "draft" | "approved" | "rejected" | "exported";
};
export type Inventory = { rows: Item[]; sequence: number };
export type Preview = {
  version: Version; body: string; editable_text: string; scope: string;
  kind: string; sequence: number; evidence: Metric[];
};
export type Bundle = {
  receipt: { export_id: string; idempotency_key: string; item_versions: Version[] };
  historical_replay: boolean; markdown_base64: string; csv_base64: string;
};

export class LocalApi {
  private csrf = "";
  async connect() {
    const response = await fetch("/api/session", { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new Error("local_service_unavailable");
    const session = await response.json() as { csrf: string; execution_origin: string };
    if (session.execution_origin !== "authored_synthetic_mock" || !session.csrf) {
      throw new Error("unsupported_local_mode");
    }
    this.csrf = session.csrf;
  }
  async post<T>(path: string, value: unknown): Promise<T> {
    if (!this.csrf) throw new Error("local_service_unavailable");
    const response = await fetch(`/api/${path}`, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": this.csrf },
      body: JSON.stringify(value),
    });
    const body = await response.json() as T & { code?: string };
    if (!response.ok) throw new Error(body.code || "request_refused");
    return body;
  }
  async example(): Promise<Uint8Array> {
    const response = await fetch("/api/example", { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new Error("example_unavailable");
    return new Uint8Array(await response.arrayBuffer());
  }
}

export function base64(bytes: Uint8Array): string {
  // Slice conversion keeps the bounded CSV off the JavaScript argument stack.
  let value = "";
  for (let offset = 0; offset < bytes.length; offset += 32768) {
    value += String.fromCharCode(...bytes.subarray(offset, offset + 32768));
  }
  return btoa(value);
}

export function receiptUrl(selection: Selection, key: string, format: "md" | "csv") {
  const parameters = new URLSearchParams({ ...selection, key });
  return `/api/download/${format}?${parameters.toString()}`;
}
