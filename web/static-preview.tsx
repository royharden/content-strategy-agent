import fixture from "./static-fixture.json";

type Row = (typeof fixture.rows)[number];
const labels: Record<string, string> = {
  ok: "Citable", insufficient_data: "Small sample", unavailable: "Unavailable",
};

function MetricTable({ rows }: { rows: Row[] }) {
  return <div className="table-wrap"><table><thead><tr><th>Metric</th><th>Canonical value</th><th>Sample</th><th>Status</th></tr></thead>
    <tbody>{rows.map(row => <tr key={row.metric.metric_id} data-fixture-status={row.metric.status}>
      <td><details><summary>{row.metric.metric_id}</summary><p>{row.metric.definition}</p><code>{row.metric.computed_by}</code>
        <p>Numerator {row.numerator} · denominator {row.denominator}</p></details><small>{row.metric.scope}</small></td>
      <td className="numeric">{row.metric.value ?? "—"}<small>{row.metric.unit}</small></td><td>{row.metric.sample_size}</td>
      <td><span className={`pill ${row.metric.status}`}>{labels[row.metric.status]}</span></td>
    </tr>)}</tbody></table></div>;
}

export function StaticPreview() {
  const citable = fixture.rows.filter(row => row.metric.status === "ok");
  const small = fixture.rows.filter(row => row.metric.status === "insufficient_data");
  const unavailable = fixture.rows.filter(row => row.metric.status === "unavailable");
  return <div className="workspace fixture-workspace">
    <aside className="rail"><a className="brand" href="#top"><span className="brand-mark">c.</span><span>content<br /><strong>strategy</strong></span></a>
      <p className="rail-caption">READ-ONLY EXAMPLE</p><nav aria-label="Example sections"><a href="#fixture-source">01 <span>Synthetic source</span></a><a href="#fixture-metrics">02 <span>Computed metrics</span></a><a href="#fixture-workflow">03 <span>Local review steps</span></a></nav>
      <div className="rail-foot"><span className="dot" />Static fixture viewer<p>No local service connection.<br />No decisions or exports.</p></div></aside>
    <main id="top"><header><div><span className="eyebrow">EXPLORE THE EVIDENCE</span><h1>A small example. Clear limits.</h1><p className="intro">See what the metrics mean before opening a local workspace. Every post in this example is explicitly synthetic.</p></div><span className="mode">Read-only example<br /><small>No live AI calls</small></span></header>
      <section className="service-notice fixture-banner"><h2>Preview without a backend</h2><p>This example displays fixed data computed by the Python analytics code. It cannot import your files, approve content, create an export receipt or save decisions. Reloading shows the same example.</p><a className="subtle download-link" href="./">Open local workspace</a><p className="fineprint">The local workspace needs the separately started Python service. A static host does not provide that service.</p></section>
      <section id="fixture-source"><div className="section-title"><div><span className="eyebrow">01 / SYNTHETIC SOURCE</span><h2>The numbers behind the example.</h2></div></div>
        <div className="summary"><div><strong>{fixture.source.rows}</strong><span>synthetic LinkedIn posts</span></div><div><strong>{citable.length}</strong><span>citable metrics</span></div><div><strong>{fixture.platforms[0].missing_time_rows}</strong><span>posts without time of day</span></div></div>
        <p>Five posts each have 100 impressions and 15 interactions; one has 1,000 impressions and 40 interactions. The overall ratio is 115 / 1,500, canonically 0.07666667. It is a ratio of sums, not an average of individual post rates.</p>
        <details className="fixture-provenance"><summary>Source and snapshot identity</summary><p>Source: {fixture.source.path}</p><code>{fixture.source.sha256}</code><p>Snapshot</p><code>{fixture.snapshot_id}</code></details>
      </section>
      <section id="fixture-metrics"><div className="section-title"><div><span className="eyebrow">02 / COMPUTED IN CODE</span><h2>Evidence with its sample size.</h2></div></div>
        <h3>Citable metrics</h3><MetricTable rows={citable} /><p className="fineprint">Canonical values retain eight fractional places. Ratios are historical diagnostics, not measured future uplift.</p>
        <details className="fixture-group"><summary>Small samples ({small.length})</summary><p>Fewer than five eligible posts cannot support a recommendation. Individual-post diagnostics remain uncitable.</p><MetricTable rows={small} /></details>
        <details className="fixture-group"><summary>Unavailable metrics ({unavailable.length})</summary><p>Missing denominators, absent time groups or insufficient comparison windows stay explicit.</p><MetricTable rows={unavailable} /></details>
      </section>
      <section id="fixture-workflow"><div className="section-title"><div><span className="eyebrow">03 / THE LOCAL WORKFLOW</span><h2>Your decisions come next.</h2></div></div>
        <ol className="fixture-steps"><li><strong>Use a snapshot.</strong> Import a CSV in the local workspace, inspect coded metrics and explicitly activate its evidence.</li><li><strong>Review a recommendation.</strong> Inspect the checked exact revision and make its separate approval decision.</li><li><strong>Review a draft.</strong> Create a draft from that approved recommendation, inspect it and decide again.</li><li><strong>Keep the approved receipt.</strong> The local service rechecks both approval stages before committing Markdown and CSV. Edits and revocation require fresh decisions.</li></ol>
        <p>No recommendation, approval or export is produced by this fixture viewer. Authored demo behavior and live model quality remain separate.</p>
      </section><footer>Example data only. <span>No publishing or scheduling</span></footer>
    </main>
  </div>;
}
