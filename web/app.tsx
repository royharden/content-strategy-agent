import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { LocalApi, base64, receiptUrl } from "./api";
import type { Bundle, Inventory, Item, Preview, Report, Selection, Version } from "./api";
import "./style.css";
import { StaticPreview } from "./static-preview";
import { rememberReceipt, saveSelection, savedReceipts, savedSelection } from "./saved-workspace";
import type { SavedReceipt } from "./saved-workspace";

const api = new LocalApi();
const sameVersion = (a: Version, b: Version) => a.item_id === b.item_id && a.revision === b.revision && a.content_hash === b.content_hash;
const message = (error: unknown) => error instanceof Error ? error.message : "request_refused";

function App() {
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [inventory, setInventory] = useState<Inventory>({ rows: [], sequence: 0 });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [chosen, setChosen] = useState<Item | null>(null);
  const [brief, setBrief] = useState("Share practical lessons with our professional community.");
  const [edit, setEdit] = useState<string | null>(null);
  const [active, setActive] = useState(false);
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [receiptSelection, setReceiptSelection] = useState<Selection | null>(null);
  const [artifact, setArtifact] = useState<"md" | "csv" | null>(null);
  const [receipts, setReceipts] = useState<SavedReceipt[]>(savedReceipts);
  const [storageWarning, setStorageWarning] = useState(false);
  const [filter, setFilter] = useState("all");
  const epoch = useRef(0);
  const operation = useRef(false);
  const file = useRef<HTMLInputElement>(null);

  async function refresh(selection: Selection) {
    const next = await api.post<Inventory>("history", { selection });
    setInventory(next);
    setChosen(current => current ? next.rows.find(row => sameVersion(row.version, current.version)) || null : null);
    return next;
  }

  async function action(task: () => Promise<void>) {
    if (operation.current) return;
    operation.current = true;
    setBusy(true); setError(""); setNotice("");
    try { await task(); }
    catch (failure) {
      setError(message(failure));
      // A failed/stale check cannot leave a formerly checked body actionable.
      setPreview(null); setEdit(null); setActive(false);
    } finally { operation.current = false; setBusy(false); }
  }

  useEffect(() => {
    let current = true;
    void api.connect().then(async () => {
      if (!current) return;
      setConnected(true);
      const selection = savedSelection();
      if (selection) {
        const restored = await api.post<Report>("report", { selection });
        if (!current) return;
        setReport(restored);
        await refresh(selection);
        setNotice("Workspace restored. Review the snapshot before using it again.");
      }
    }).catch(failure => { if (current) setError(message(failure)); }).finally(() => { if (current) setBusy(false); });
    return () => { current = false; };
  }, []);

  async function importBytes(bytes: Uint8Array) {
    if (bytes.length > 10 * 1024 * 1024) throw new Error("csv_too_large");
    epoch.current += 1;
    setPreview(null); setChosen(null); setEdit(null); setBundle(null); setActive(false);
    const imported = await api.post<{ selection: Selection; sequence: number }>("import", { csv_base64: base64(bytes), clock: "posted-local" });
    const next = await api.post<Report>("report", { selection: imported.selection });
    setReport(next);
    await refresh(imported.selection);
    if (!saveSelection(imported.selection)) setStorageWarning(true);
    setNotice("CSV retained. Metrics are computed in code. Use this snapshot to begin review.");
  }

  async function inspect(item: Item) {
    if (!report) return;
    setPreview(null); setChosen(item); setEdit(null);
    const started = epoch.current;
    const checked = await api.post<Preview>("preview", { selection: report.selection, version: item.version, expected_sequence: inventory.sequence });
    if (started === epoch.current) setPreview(checked);
  }

  async function decide(approve: boolean) {
    if (!report || !chosen || !preview) return;
    await api.post("decide", { selection: report.selection, version: preview.version, expected_sequence: preview.sequence, approve });
    await refresh(report.selection);
    setPreview(null); setNotice(approve ? "This exact revision is approved." : "This revision was rejected.");
  }

  async function draft() {
    if (!report || !chosen || !preview) return;
    const result = await api.post<{ version: Version | null; sequence: number; dropped_codes: string[][] }>("draft", {
      selection: report.selection, version: preview.version, expected_sequence: preview.sequence, brief,
    });
    await refresh(report.selection);
    setPreview(null);
    if (!result.version) throw new Error(result.dropped_codes.flat().join(", ") || "draft_refused");
    setNotice("Draft created. Inspect and approve it separately before exporting.");
  }

  function remember(selection: Selection, key: string) {
    const remembered = rememberReceipt(selection, key, receipts);
    setReceipts(remembered.receipts);
    if (!remembered.persisted) setStorageWarning(true);
  }

  async function exportChosen() {
    if (!report || !chosen || !preview) return;
    const key = "web-" + crypto.randomUUID();
    // Keep the lookup key before dispatch: receipt recovery also covers a lost response.
    remember(report.selection, key);
    const result = await api.post<Bundle>("export", { selection: report.selection, items: [preview.version], expected_sequence: preview.sequence, idempotency_key: key });
    setBundle(result); setReceiptSelection(report.selection); setPreview(null);
    await refresh(report.selection);
    setNotice("Approved bytes committed. Both downloads come from the same immutable receipt.");
  }

  async function recover(saved: SavedReceipt) {
    setBundle(await api.post<Bundle>("receipt", { selection: saved.selection, idempotency_key: saved.key }));
    setReceiptSelection(saved.selection);
    setNotice("Historical receipt recovered. This does not approve changed content.");
  }

  const latest = inventory.rows.filter(row => !inventory.rows.some(other => other.version.item_id === row.version.item_id && other.version.revision > row.version.revision));
  const recommendations = latest.filter(row => row.kind === "recommendation");
  const drafts = latest.filter(row => row.kind === "draft");
  const metrics = report?.rows.filter(row => filter === "all" || row.metric.status === filter) || [];
  const approved = chosen?.state === "approved" || chosen?.state === "exported";
  const artifactText = bundle && artifact ? new TextDecoder().decode(Uint8Array.from(atob(artifact === "md" ? bundle.markdown_base64 : bundle.csv_base64), character => character.charCodeAt(0))) : "";

  const cards = (items: Item[], empty: string) => <div className="cards">{items.length ? items.map((item, index) => <button key={item.version.item_id} className={`item-card ${chosen && sameVersion(chosen.version, item.version) ? "selected" : ""}`} disabled={busy || !active} onClick={() => void action(() => inspect(item))}>
    <span className="card-label">{item.kind === "draft" ? "Draft" : "Recommendation"} {index + 1}</span>
    <span className={`pill ${item.state}`}>{item.state}</span><span className="revision">Revision {item.version.revision} <span aria-hidden="true">↗</span></span>
  </button>) : <p className="empty">{empty}</p>}</div>;

  return <div className="workspace">
    <aside className="rail"><a className="brand" href="#top"><span className="brand-mark">c.</span><span>content<br /><strong>strategy</strong></span></a>
      <p className="rail-caption">LOCAL WORKSPACE</p><nav aria-label="Workflow"><a href="#source">01 <span>Source & metrics</span></a><a href="#strategy">02 <span>Strategy</span></a><a href="#drafts">03 <span>Draft review</span></a><a href="#export">04 <span>Approved exports</span></a></nav>
      <div className="rail-foot"><span className={`dot ${connected ? "online" : ""}`} />{connected ? "Local service connected" : "Static preview"}<p>Your decisions stay local.<br />No publishing or scheduling.</p></div>
    </aside>
    <main id="top"><header><div><span className="eyebrow">EVIDENCE BEFORE CONTENT</span><h1>A strategy you can trace.</h1><p className="intro">Turn past posts into grounded ideas. Review the evidence, make the decisions, keep the final word.</p></div><span className="mode">Authored demo<br /><small>No live AI calls</small></span></header>
      {!connected && <section className="service-notice"><h2>Connect the local review service</h2><p>This static preview cannot approve content or export it. Start the local backend and open the URL it provides. The complete terminal workflow is also available.</p><code>python -m content_strategy serve --help</code><p><a className="subtle download-link" href="?preview=fixture">Explore a read-only example</a></p></section>}
      <div aria-live="polite" className="messages">{error && <div role="alert" className="alert"><strong>Action blocked</strong><span>{error.replaceAll("_", " ")}</span><small>Existing approvals are never inferred from this screen. Refresh and review the current snapshot.</small></div>}{notice && <p className="notice">{notice}</p>}{storageWarning && <p className="notice">Recovery pointers could not be saved in this browser. Keep this tab open and copy receipt lookup keys before closing.</p>}{busy && <p className="working" role="status">Checking the current evidence and revision…</p>}</div>
      <section id="source"><div className="section-title"><div><span className="eyebrow">01 / THE SOURCE</span><h2>Start with what happened.</h2></div><span className="muted">CSV · up to 5,000 posts</span></div>
        <div className="import-panel"><div><h3>Past posts, clear evidence.</h3><p>Import a CSV with dates, platforms and engagement counts. Topic and format labels are optional.</p><details><summary>CSV columns</summary><code>post_id, date, platform, text, impressions, likes, comments, shares, topic, format</code></details></div><div className="import-actions"><input ref={file} type="file" accept=".csv,text/csv" aria-label="Import CSV" disabled={busy || !connected} onChange={event => { const upload = event.target.files?.[0]; if (upload) void action(async () => importBytes(new Uint8Array(await upload.arrayBuffer()))); event.target.value = ""; }} /><button className="primary" disabled={busy || !connected} onClick={() => file.current?.click()}>Import CSV <span aria-hidden="true">↑</span></button><button className="text-button" disabled={busy || !connected} onClick={() => void action(async () => importBytes(await api.example()))}>Try synthetic example</button></div></div>
        {report && <><div className="summary"><div><strong>{report.platforms.reduce((sum, platform) => sum + platform.rows, 0)}</strong><span>posts retained</span></div><div><strong>{report.rows.filter(row => row.metric.status === "ok").length}</strong><span>citable metrics</span></div><div><strong>{report.rows.filter(row => row.metric.status !== "ok").length}</strong><span>unavailable or small sample</span></div><button className={active ? "subtle" : "primary"} disabled={busy || active} onClick={() => void action(async () => { const result = await api.post<{ sequence: number }>("activate", { selection: report.selection, expected_sequence: inventory.sequence }); setInventory(current => ({ ...current, sequence: result.sequence })); setActive(true); setPreview(null); setNotice("Snapshot active. Changed evidence or policy invalidates prior approvals."); })}>{active ? "Snapshot active" : "Use this snapshot"}</button></div>
          <div className="table-heading"><h3>Computed metrics</h3><label>Show <select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All statuses</option><option value="ok">Citable</option><option value="insufficient_data">Small samples</option><option value="unavailable">Unavailable</option></select></label></div><div className="table-wrap"><table><thead><tr><th>Metric / platform</th><th>Exact value</th><th>Sample</th><th>Evidence status</th></tr></thead><tbody>{metrics.map(row => <tr key={row.metric.metric_id}><td><details><summary>{row.metric.metric_id}</summary><p>{row.metric.definition}</p><code>{row.metric.computed_by}</code></details><small>{row.metric.scope}</small></td><td className="numeric">{row.metric.value ?? "—"}<small>{row.metric.unit}</small></td><td>{row.metric.sample_size}</td><td><span className={`pill ${row.metric.status}`}>{row.metric.status === "ok" ? "Citable" : row.metric.status === "insufficient_data" ? "Small sample" : "Unavailable"}</span></td></tr>)}</tbody></table></div><p className="fineprint">Metrics with fewer than five eligible posts cannot support a recommendation. Diagnostic single-post values remain uncitable. Rates are not measured uplift.</p></>}
      </section>
      <section id="strategy"><div className="section-title"><div><span className="eyebrow">02 / THE STRATEGY</span><h2>Ideas with a paper trail.</h2></div></div><label className="field">Content brief<textarea maxLength={4000} value={brief} disabled={busy} onChange={event => setBrief(event.target.value)} /></label><div className="row-actions"><button className="primary" disabled={busy || !active || !report} onClick={() => void action(async () => { if (!report) return; const result = await api.post<{ versions: Version[]; underfilled: boolean; dropped_codes: string[][] }>("plan", { selection: report.selection, expected_sequence: inventory.sequence, brief }); await refresh(report.selection); setPreview(null); setNotice(result.versions.length ? `${result.versions.length} checked demo recommendations. Approve an exact revision before drafting.` : "No recommendations survived. Citable evidence is required."); })}>Create demo strategy</button><p className="fineprint">Authored synthetic generation, screening and support judgments. This demonstrates the workflow, not model quality.</p></div>{cards(recommendations, "Your checked recommendations will appear here after a snapshot is active.")}</section>
      <section id="drafts"><div className="section-title"><div><span className="eyebrow">03 / THE REVIEW</span><h2>Every draft earns its approval.</h2></div></div>{cards(drafts, "Approve a recommendation, then create a draft from its checked review.")}
        {chosen && preview && <article className="review-panel"><div className="review-heading"><div><span className="eyebrow">{preview.scope} / {preview.kind}</span><h3>Review this exact revision</h3></div><span className={`pill ${chosen.state}`}>{chosen.state}</span></div><p className="review-body">{preview.body}</p><details><summary>Evidence & revision</summary><code>{preview.version.content_hash}</code><ul>{preview.evidence.map(metric => <li key={metric.metric_id}>{metric.metric_id}: <strong>{metric.value} {metric.unit}</strong> · n={metric.sample_size}</li>)}</ul></details><div className="row-actions">{chosen.state === "draft" && <><button className="primary" disabled={busy} onClick={() => void action(() => decide(true))}>Approve {chosen.kind}</button><button className="subtle" disabled={busy} onClick={() => void action(() => decide(false))}>Reject revision</button></>}{approved && chosen.kind === "recommendation" && <button className="primary" disabled={busy} onClick={() => void action(draft)}>Create draft from approved recommendation</button>}{approved && <button className="danger" disabled={busy} onClick={() => void action(async () => { if (!report) return; await api.post("revoke", { selection: report.selection, version: preview.version, expected_sequence: preview.sequence }); await refresh(report.selection); setPreview(null); setNotice("Approval revoked. Dependent approvals require fresh decisions."); })}>Revoke approval</button>}<button className="text-button" disabled={busy || chosen.state === "rejected"} onClick={() => setEdit(preview.editable_text)}>Edit & revalidate</button></div>{edit !== null && <div className="edit-panel"><label className="field">Edit the draft text; retain evidence placeholders<textarea value={edit} maxLength={16384} onChange={event => setEdit(event.target.value)} /></label><p className="fineprint">Saving creates a new revision and removes dependent approvals. Unsupported numbers or citations are refused.</p><button className="subtle" disabled={busy} onClick={() => void action(async () => { if (!report) return; const edited = await api.post<{ version: Version | null; dropped_codes: string[][] }>("edit", { selection: report.selection, version: preview.version, expected_sequence: preview.sequence, text: edit }); await refresh(report.selection); setPreview(null); setEdit(null); if (!edited.version) throw new Error(edited.dropped_codes.flat().join(", ") || "edit_refused"); setNotice("New revision saved. Inspect it and approve it again."); })}>Save new revision</button></div>}</article>}
      </section>
      <section id="export"><div className="section-title"><div><span className="eyebrow">04 / YOUR DECISION</span><h2>Only approved words leave.</h2></div></div><div className="export-panel"><div><h3>One receipt. Two formats.</h3><p>Select and inspect an approved draft above. The server rechecks both approval stages before committing Markdown and CSV together.</p></div><button className="primary" disabled={busy || !preview || chosen?.kind !== "draft" || !approved} onClick={() => void action(exportChosen)}>Export approved draft <span aria-hidden="true">↓</span></button></div>{bundle && <div className="download-panel"><strong>{bundle.historical_replay ? "Historical receipt recovered" : "Approved bundle ready"}</strong><p className="fineprint">{bundle.receipt.export_id}</p>{receiptSelection && <><a className="subtle download-link" href={receiptUrl(receiptSelection, bundle.receipt.idempotency_key, "md")} download="approved-content.md">Download Markdown</a><a className="subtle download-link" href={receiptUrl(receiptSelection, bundle.receipt.idempotency_key, "csv")} download="approved-content.csv">Download CSV</a></>}<div className="row-actions"><button className="text-button" onClick={() => setArtifact("md")}>View Markdown</button><button className="text-button" onClick={() => setArtifact("csv")}>View CSV</button></div>{artifact && <label className="field artifact-view">Approved {artifact === "md" ? "Markdown" : "CSV"}<textarea readOnly rows={7} value={artifactText} onFocus={event => event.target.select()} /></label>}<p className="fineprint">These committed bytes remain historical evidence even if an approval is later revoked.</p></div>}{receipts.length > 0 && <details className="receipts"><summary>Recover an export after restart ({receipts.length})</summary><p>Saved keys are lookup pointers. Every download still requires the server's stored receipt. An interrupted request may have no receipt.</p>{receipts.map(saved => <button className="receipt-link" key={JSON.stringify([saved.selection, saved.key])} disabled={busy || !connected} onClick={() => void action(() => recover(saved))}>{saved.key}<span>Recover →</span></button>)}</details>}</section>
      <footer>Made for considered decisions. <span>Local SQLite · exact evidence · no publishing</span></footer>
    </main>
  </div>;
}

createRoot(document.getElementById("root")!).render(
  new URL(window.location.href).searchParams.get("preview") === "fixture" ? <StaticPreview /> : <App />,
);
