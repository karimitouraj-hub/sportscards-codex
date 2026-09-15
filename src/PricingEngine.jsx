import React from "react";
import { api, money, cents } from "./api";
import { Field, Modal, Notice } from "./ui";
import "./pricing-engine.css";

const sourceNames = { sold: "Sold evidence", active_listing: "Listing scenario", unknown: "No price reference" };
const strategies = { individual: "Individual sales", bundle: "Bundles", hold: "Hold all cards", markdown: "Scheduled price reduction" };
const percent = value => value == null ? "Not estimated" : `${(value * 100).toFixed(1)}%`;
const date = value => value ? new Date(value).toLocaleDateString() : "Unknown";
const cardCount = value => `${value ?? "Unknown"} ${value === 1 ? "card" : "cards"}`;
const feeLabel = costs => costs.fee_model === "ebay_us_non_store"
  ? `${costs.percent}% through ${money(costs.tier_threshold_cents)} per sold item; ${costs.excess_percent}% above`
  : `${costs.percent}% flat scenario`;
const sourceMoney = (value, currency = "USD") => value == null ? "Not estimated" : new Intl.NumberFormat("en-US", { style: "currency", currency }).format(value / 100);
const settingFields = [
  ["listing_factor", "Fraction of asking price", 0.8, 0, 2],
  ["p30", "Chance of sale in 30 days", 0.35, 0, 1],
  ["market_sigma", "Shared market variation", 0.15, 0, 2],
  ["player_sigma", "Shared player variation", 0.15, 0, 2],
  ["product_sigma", "Shared product variation", 0.1, 0, 2],
  ["card_sigma", "Card price variation", 0.2, 0, 2],
];

function SettingFields({ settings }) {
  return <div className="form-grid">{settingFields.map(([key, label, fallback, min, max]) => <Field key={key} label={label} name={key} type="number" min={min} max={max} step="0.01" defaultValue={settings?.[key] ?? fallback} required />)}</div>;
}

function Settings({ settings, onSaved }) {
  const [error, setError] = React.useState(""), [busy, setBusy] = React.useState(false), [saved, setSaved] = React.useState(false);
  async function save(e) {
    e.preventDefault(); setBusy(true); setError(""); setSaved(false);
    const form = new FormData(e.currentTarget);
    try { await api("/pricing-settings", "PATCH", Object.fromEntries(settingFields.map(([key]) => [key, Number(form.get(key))]))); await onSaved(); setSaved(true); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <details className="pe-panel"><summary>Default scenario assumptions</summary>
    <p>These inputs are assumptions. The collection does not yet contain enough tracked outcomes to fit a price or sale-probability model.</p>
    <p>Use fractions: 0.80 means 80%. Variation controls the spread of simulated prices. Shared factors move related cards together.</p>
    <form onSubmit={save} key={JSON.stringify(settings)}><SettingFields settings={settings} /><button disabled={busy}>{busy ? "Saving..." : "Save default assumptions"}</button></form>
    {error && <p role="alert" className="error">{error}</p>}{saved && <p className="save-status" role="status">Default assumptions saved. Existing runs keep their original inputs.</p>}
  </details>;
}

function ListingDetail({ row, card, onClose, onSaved, onSimulate, onCard }) {
  const [data, setData] = React.useState(null), [error, setError] = React.useState(""), [busy, setBusy] = React.useState(false);
  const load = React.useCallback(() => api(`/cards/${card.id}/listings`).then(setData), [card.id]);
  React.useEffect(() => { let active = true; api(`/cards/${card.id}/listings`).then(result => { if (active) setData(result); }).catch(err => { if (active) setError(err.message); }); return () => { active = false; }; }, [card.id]);
  async function addListing(event) {
    event.preventDefault(); setBusy(true); setError("");
    const element = event.currentTarget, form = Object.fromEntries(new FormData(element));
    try {
      await api(`/cards/${card.id}/listings`, "POST", {
        revision: data.revision, match_reviewed: true, ask_cents: cents(form.ask), shipping_cents: cents(form.shipping), shipping_known: true,
        currency: "USD", status: "active", observed_at: form.observed_at === new Date().toISOString().slice(0, 10) ? new Date().toISOString() : new Date(`${form.observed_at}T12:00:00Z`).toISOString(),
        source_url: form.source_url, source_title: form.source_title, seller: form.seller, physical_copy_key: form.physical_copy_key,
        buying_format: "fixed_price", evidence_state: "user_entered", notes: form.notes,
      });
      element.reset(); await load(); await onSaved();
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  const included = new Set(row.active_included || []);
  return <Modal title={`${card.player}: price evidence`} onClose={onClose} wide><div className="pe-detail">
    <p>{[card.year, card.set, card.variant, card.serial_number].filter(Boolean).join(" · ")}</p>
    <span className={`pe-source ${row.price_source}`}>{sourceNames[row.price_source]}</span>
    <div className="pe-metrics">
      <Metric label="Purchase cost" value={money(row.purchase_cost_cents)} />
      <Metric label="Sold estimate" value={money(row.sold_value_cents)} detail={`${row.sold_sample_count} qualifying sales`} />
      <Metric label="Delivered asking reference" value={money(row.active_ask_cents)} detail={`${row.active_sample_count} listings · ${row.active_seller_count} sellers`} />
      <Metric label="Listing sale scenario" value={money(row.listing_scenario_cents)} detail="Uses the assumed fraction of asks" />
    </div>
    <p>{row.confidence}. {row.active_range_cents && <>Asking prices range from {money(row.active_range_cents[0])} to {money(row.active_range_cents[1])}. </>}First observed: {date(row.first_observed_at)}. Latest observation: {date(row.latest_observed_at)}.</p>
    {row.active_quantiles_cents && <p className="muted">Middle half of asking prices: {money(row.active_quantiles_cents.p25)} to {money(row.active_quantiles_cents.p75)}. {row.active_unknown_seller_count || 0} included listings have an unknown seller.</p>}
    <p className="muted">An asking price is a seller's offer. It does not establish a sale price. First observation is not the listing date.</p>
    <div className="pe-actions"><button onClick={() => onSimulate(card.id)}>Simulate this card</button><button onClick={() => onCard(card)}>Open purchase and sold evidence</button></div>
    {error && <p role="alert" className="error">{error}</p>}
    <h3>Active listing records</h3>
    {!data ? <p role="status">Loading listing records...</p> : !data.listings.length ? <p>No active listing records are saved for this card.</p> : data.listings.map(item => <article className="pe-evidence" key={item.id}>
      <div><a href={item.source_url} target="_blank" rel="noreferrer">{item.source_title || "View listing"}</a><p>Observed {date(item.observed_at || item.last_observed_at)} · Seller {item.seller || "unknown"}</p><small>{item.notes}</small><p><span className={`pe-source ${included.has(item.id) ? "active_listing" : "unknown"}`}>{included.has(item.id) ? "Included in reference" : "Excluded from reference"}</span></p></div>
      <strong>{sourceMoney(item.ask_cents + (item.shipping_known ? item.shipping_cents : 0), item.currency)}<small>{item.shipping_known ? "Includes buyer shipping" : "Shipping is unknown"} · {item.currency}</small></strong>
    </article>)}
    {!!row.active_excluded?.length && <details><summary>{row.active_excluded.length} excluded records</summary>{row.active_excluded.map(record => <p key={record.id}>{record.reasons.join(" ")}</p>)}</details>}
    {(data?.research || row.listing_research) && <details open><summary>Listing research record</summary>{row.listing_research_current === false && <p className="muted">The card identity changed after this review. Review the research again.</p>}<ResearchNote research={data?.research || row.listing_research} /></details>}
    <details className="pe-panel"><summary>Add a reviewed fixed-price listing</summary>
      <p>Match the player, year, set, parallel, print run, autograph, memorabilia, and raw or graded condition.</p>
      <form onSubmit={addListing}><div className="form-grid">
        <Field label="Listing URL" name="source_url" type="url" required maxLength="2000" />
        <Field label="Listing title" name="source_title" required maxLength="1000" />
        <Field label="Asking price (USD)" name="ask" type="number" min="0.01" step="0.01" required />
        <Field label="Buyer shipping (USD)" name="shipping" type="number" min="0" step="0.01" required />
        <Field label="Date observed" name="observed_at" type="date" defaultValue={new Date().toISOString().slice(0, 10)} max={new Date().toISOString().slice(0, 10)} required />
        <Field label="Seller" name="seller" maxLength="250" />
        <Field label="Physical copy identifier, if known" name="physical_copy_key" maxLength="250" />
        <Field label="Match notes" name="notes" maxLength="2000" />
      </div><label className="pe-check"><input type="checkbox" required />I reviewed the exact card variant. This listing is active, fixed price, and for one card. Shipping is known.</label>
      <button disabled={busy || !data}>{busy ? "Saving listing..." : "Save reviewed listing"}</button></form>
    </details>
  </div></Modal>;
}

function ResearchNote({ research }) {
  return <><p>Reviewed {date(research.reviewed_at)}. {research.query && <>Query: {research.query}.</>}</p><p>{research.limitations}</p>{research.url && <a href={research.url} target="_blank" rel="noreferrer">Search source</a>}</>;
}

function Metric({ label, value, detail }) {
  return <div className="pe-metric"><small>{label}</small><strong className={String(value).startsWith("-") ? "pe-negative" : undefined}>{value}</strong>{detail && <span>{detail}</span>}</div>;
}

function PriceList({ report, state, selected, setSelected, onDetail, onSimulate }) {
  const [query, setQuery] = React.useState(""), [filter, setFilter] = React.useState("all"), [sort, setSort] = React.useState("cost");
  const cards = React.useMemo(() => new Map(state.cards.map(card => [card.id, card])), [state.cards]);
  const observations = React.useMemo(() => { const result = new Map(); for (const item of state.observations) { if (!result.has(item.card_id)) result.set(item.card_id, item); } for (const card of state.cards) { const primary = state.observations.find(item => item.id === card.primary_observation_id); if (primary) result.set(card.id, primary); } return result; }, [state.cards, state.observations]);
  const rows = report.rows.filter(row => {
    const card = cards.get(row.card_id); return card && (filter === "all" || row.price_source === filter) && [row.label, card.player, card.set, card.variant, card.serial_number].join(" ").toLowerCase().includes(query.toLowerCase());
  }).sort((a, b) => sort === "name" ? a.label.localeCompare(b.label) : (b[sort === "cost" ? "purchase_cost_cents" : "scenario_price_cents"] ?? -Infinity) - (a[sort === "cost" ? "purchase_cost_cents" : "scenario_price_cents"] ?? -Infinity));
  function toggle(id) { setSelected(previous => { const next = new Set(previous); next.has(id) ? next.delete(id) : next.add(id); return next; }); }
  return <>
    <div className="pe-toolbar"><input aria-label="Search pricing cards" placeholder="Search player, set, or serial" value={query} onChange={e => setQuery(e.target.value)} /><select aria-label="Price source" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All price sources</option>{Object.entries(sourceNames).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><select aria-label="Sort pricing cards" value={sort} onChange={e => setSort(e.target.value)}><option value="cost">Highest purchase cost</option><option value="price">Highest scenario price</option><option value="name">Player name</option></select></div>
    <div className="pe-actions pe-list-actions"><span>{rows.length} cards shown · {selected.size} selected</span><button onClick={() => setSelected(new Set(rows.map(row => row.card_id)))}>Select shown</button><button disabled={!selected.size} onClick={() => setSelected(new Set())}>Clear selection</button><button disabled={!selected.size} onClick={onSimulate}>Simulate selected</button><a href="/api/export/pricing-csv" download>Pricing CSV</a></div>
    <div className="pe-card-list">{rows.map(row => { const card = cards.get(row.card_id), observation = observations.get(card.id); return <article className="pe-card" key={card.id}>
      <label className="pe-card-select"><input type="checkbox" checked={selected.has(card.id)} onChange={() => toggle(card.id)} aria-label={`Select ${card.player} ${card.variant} ${card.serial_number || ""}`} /></label>
      <button className="pe-card-open" onClick={() => onDetail(row)}>
        {observation ? <img src={`/media/crop/${observation.id}?v=${observation.crop_revision || 0}`} alt={`${card.player} card`} loading="lazy" /> : <div className="pe-no-image">No photo</div>}
        <div className="pe-card-identity"><h3>{card.player}</h3><p>{[card.year, card.set, card.variant].filter(Boolean).join(" · ")}</p><small>{card.serial_number ? `Serial ${card.serial_number} · ` : ""}{row.sold_sample_count} sales · {row.active_sample_count} active listings</small><span className={`pe-source ${row.price_source}`}>{sourceNames[row.price_source]}</span></div>
        <div className="pe-card-prices"><div><small>Paid</small><strong>{money(row.purchase_cost_cents)}</strong></div><div><small>{row.price_source === "sold" ? "Sold estimate" : "Listing scenario"}</small><strong>{money(row.scenario_price_cents)}</strong></div><div><small>Asking reference</small><strong>{money(row.active_ask_cents)}</strong></div><div><small>Scenario net</small><strong>{money(row.scenario_net_cents)}</strong></div></div>
      </button>
    </article>; })}</div>{!rows.length && <p>No cards match this filter.</p>}
  </>;
}

export default function PricingEngine({ state, refresh, onCard }) {
  const [report, setReport] = React.useState(null), [error, setError] = React.useState(""), [section, setSection] = React.useState("prices"), [selected, setSelected] = React.useState(new Set()), [detailId, setDetailId] = React.useState(null), [run, setRun] = React.useState(null), [history, setHistory] = React.useState([]);
  const revisionKey = state.cards.map(card => `${card.id}:${card.revision}`).join("|");
  const reload = React.useCallback(async () => { const [nextReport, nextHistory] = await Promise.all([api("/pricing-engine"), api("/pricing-engine/runs")]); setReport(nextReport); setHistory(nextHistory.runs); }, []);
  React.useEffect(() => { let active = true; Promise.all([api("/pricing-engine"), api("/pricing-engine/runs")]).then(([nextReport, nextHistory]) => { if (active) { setReport(nextReport); setHistory(nextHistory.runs); } }).catch(err => { if (active) setError(err.message); }); return () => { active = false; }; }, [revisionKey]);
  async function saved() { await refresh(); await reload(); }
  async function loadRun(id) { setError(""); try { const savedRun = await api(`/pricing-engine/runs/${id}`); setRun(savedRun); setSection(savedRun.type === "release" ? "releases" : "simulate"); } catch (err) { setError(err.message); } }
  async function completed(value) { setRun(value); const next = await api("/pricing-engine/runs"); setHistory(next.runs); }
  function simulateCard(id) { setSelected(new Set([id])); setDetailId(null); setSection("simulate"); }
  if (!report) return <><p role={error ? "alert" : "status"}>{error || "Loading price references and scenario engine..."}</p>{error && <button onClick={() => reload().then(() => setError("")).catch(err => setError(err.message))}>Retry pricing engine</button>}</>;
  const sold = report.rows.filter(row => row.price_source === "sold"), listing = report.rows.filter(row => row.price_source === "active_listing"), unknown = report.rows.filter(row => row.price_source === "unknown");
  const detailRow = report.rows.find(row => row.card_id === detailId), detailCard = state.cards.find(card => card.id === detailId);
  return <div className="pricing-engine">
    {error && <p role="alert" className="error">{error}</p>}
    <div className="pe-metrics pe-summary"><Metric label="Sold-supported estimates" value={money(report.summary.sold_value_cents)} detail={`${sold.length} of ${report.rows.length} cards`} /><Metric label="Listing sale scenarios" value={money(report.summary.listing_scenario_cents)} detail={`${listing.length} additional cards · assumption ${percent(report.settings.listing_factor)}`} /><Metric label="No price reference" value={unknown.length} detail={`${money(unknown.reduce((sum, row) => sum + (row.purchase_cost_cents || 0), 0))} known purchase cost remains unmodeled`} /><Metric label="Collection purchase cost" value={money(report.summary.purchase_cost_cents)} detail={`${report.rows.length} physical cards · ${report.summary.unknown_purchase_cost_cards} costs unknown`} /></div>
    <Notice>Sold estimates and listing scenarios use different evidence. Asking prices are observed offers. Sale probabilities and future price changes remain assumptions.</Notice>
    <div className="pe-actions"><span className="pe-subtitle">Listing observations qualify for 14 days. Sold evidence qualifies for 90 days.</span><button onClick={() => reload().catch(err => setError(err.message))}>Reload saved evidence</button></div>
    <nav className="pe-tabs" aria-label="Pricing engine sections">{[["prices", "Card prices"], ["simulate", "Simulations"], ["releases", "New releases"], ["history", "Saved runs"]].map(([key, label]) => <button key={key} aria-current={section === key ? "page" : undefined} className={section === key ? "selected" : ""} onClick={() => setSection(key)}>{label}</button>)}</nav>
    {section === "prices" && <><p className="pe-subtitle">Listing sale scenario = median(asking price + buyer shipping) × {report.settings.listing_factor.toFixed(2)}. Sold evidence takes priority when it qualifies.</p><Settings settings={report.settings} onSaved={reload} /><PriceList report={report} state={state} selected={selected} setSelected={setSelected} onDetail={row => setDetailId(row.card_id)} onSimulate={() => setSection("simulate")} /></>}
    {section === "simulate" && <SimulationPanel report={report} selected={selected} setSelected={setSelected} onCompleted={completed} run={run?.type === "collection" ? run : null} />}
    {section === "releases" && <ReleasePanel report={report} onCompleted={completed} run={run?.type === "release" ? run : null} />}
    {section === "history" && <RunHistory history={history} onLoad={loadRun} />}
    {detailRow && detailCard && <ListingDetail row={detailRow} card={detailCard} onClose={() => setDetailId(null)} onSaved={saved} onSimulate={simulateCard} onCard={card => { setDetailId(null); onCard(card); }} />}
  </div>;
}

function SimulationPanel({ report, selected, setSelected, onCompleted, run }) {
  const [busy, setBusy] = React.useState(false), [error, setError] = React.useState(""), [strategy, setStrategy] = React.useState("individual"), [scope, setScope] = React.useState(selected.size ? "selected" : "all");
  const count = scope === "selected" ? selected.size : report.rows.length;
  const scoped = scope === "selected" ? report.rows.filter(row => selected.has(row.card_id)) : report.rows;
  const unknownCount = scoped.filter(row => row.price_source === "unknown").length;
  async function simulate(event) {
    event.preventDefault(); setBusy(true); setError("");
    const form = new FormData(event.currentTarget);
    const options = Object.fromEntries(settingFields.map(([key]) => [key, Number(form.get(key))]));
    Object.assign(options, { strategy, horizon_days: Number(form.get("horizon_days")), trials: Number(form.get("trials")), seed: Number(form.get("seed")) });
    if (scope === "selected") options.card_ids = [...selected];
    if (strategy === "bundle") Object.assign(options, {
      bundle_size: Number(form.get("bundle_size")), bundle_price_factor: Number(form.get("bundle_price_factor")), bundle_p30: Number(form.get("bundle_p30")),
      bundle_shipping_cents: cents(form.get("bundle_shipping")), bundle_packaging_cents: cents(form.get("bundle_packaging")),
    });
    if (strategy === "markdown") Object.assign(options, { markdown_after_days: Number(form.get("markdown_after_days")), markdown_price_factor: Number(form.get("markdown_price_factor")), markdown_p30: Number(form.get("markdown_p30")) });
    try { await onCompleted(await api("/pricing-engine/simulate", "POST", options)); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <>
    <section className="pe-panel"><div className="pe-form-title"><h2>Test a selling strategy</h2><span className="pe-source active_listing">Uncalibrated scenario</span></div>
      <p>Run seeded trials against the current collection. Unsold cards stay in inventory. Unknown price references stay outside the price model.</p>
      <form onSubmit={simulate} key={JSON.stringify(report.settings)}>
        <div className="form-grid">
          <Field label="Cards to simulate"><select value={scope} onChange={e => setScope(e.target.value)}><option value="all">Whole collection ({report.rows.length} cards)</option><option value="selected" disabled={!selected.size}>Selected cards ({selected.size})</option></select></Field>
          <Field label="Selling strategy"><select value={strategy} onChange={e => setStrategy(e.target.value)}>{Object.entries(strategies).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
          <Field label="Time horizon"><select name="horizon_days" defaultValue="90"><option value="30">30 days</option><option value="90">90 days</option><option value="180">180 days</option></select></Field>
          <Field label="Simulation trials"><select name="trials" defaultValue="10000"><option value="10000">10,000 trials</option><option value="1000">1,000 trials</option></select></Field>
          <Field label="Random seed" name="seed" type="number" min="0" max="2147483647" step="1" defaultValue="42" required />
        </div>
        <div className="pe-scope"><p>{count} cards selected. {count - unknownCount} have a price reference. {unknownCount} have no price reference.</p>{scope === "selected" && <button type="button" onClick={() => { setScope("all"); setSelected(new Set()); }}>Use the whole collection</button>}</div>
        {strategy === "hold" && <Notice>The hold strategy makes no sales. It reports retained cost and modeled terminal inventory value separately.</Notice>}
        {strategy === "bundle" && <div className="pe-panel"><h3>Bundle assumptions</h3><p>Each bundle uses one lot listing and one shipment. Bundle price and sale probability are separate assumptions.</p><p>Groups follow the saved card order. Review whether those cards make suitable bundles before using the results.</p><div className="form-grid">
          <Field label="Cards per bundle" name="bundle_size" type="number" min="2" max="100" step="1" defaultValue="5" required />
          <Field label="Bundle price fraction" name="bundle_price_factor" type="number" min="0" max="2" step="0.01" defaultValue="0.85" required />
          <Field label="Bundle sale chance in 30 days" name="bundle_p30" type="number" min="0" max="1" step="0.01" defaultValue="0.35" required />
          <Field label="Postage per bundle (USD)" name="bundle_shipping" type="number" min="0" max="10000" step="0.01" defaultValue="7.00" required />
          <Field label="Packaging per bundle (USD)" name="bundle_packaging" type="number" min="0" max="10000" step="0.01" defaultValue="1.00" required />
        </div></div>}
        {strategy === "markdown" && <div className="pe-panel"><h3>Scheduled price reduction</h3><p>The reduced price applies after the selected day. A lower price does not automatically increase the chance of sale.</p><div className="form-grid">
          <Field label="Reduce price after days" name="markdown_after_days" type="number" min="0" max="3650" step="1" defaultValue="30" required />
          <Field label="Reduced price fraction" name="markdown_price_factor" type="number" min="0" max="2" step="0.01" defaultValue="0.85" required />
          <Field label="Sale chance in 30 days after reduction" name="markdown_p30" type="number" min="0" max="1" step="0.01" defaultValue="0.35" required />
        </div></div>}
        <details className="pe-panel"><summary>Price and sale-probability assumptions</summary><p>Use fractions: 0.35 means a 35% chance of sale in 30 days. These inputs apply only to this run.</p><SettingFields settings={report.settings} /></details>
        <p className="pe-subtitle">Individual shipment assumptions: {money(report.costs.shipping_cents)} postage and {money(report.costs.packaging_cents)} packaging. Fee: {feeLabel(report.costs)}. The fee base includes {report.costs.tax_percent}% assumed buyer tax. Edit these on Analysis.</p>
        <div className="pe-run-status"><button className="primary" disabled={busy || !count}>{busy ? "Running simulation..." : "Run and save simulation"}</button>{busy && <span role="status">The server is running the trials. Results will appear here.</span>}</div>
        {error && <p role="alert" className="error">{error}</p>}
      </form>
    </section>
    {run && <RunResults run={run} />}
  </>;
}

function QuantileTable({ metrics }) {
  const rows = [["net_cash_cents", "Net cash recovered", money], ["realized_profit_cents", "Realized profit / loss", money], ["gross_sales_cents", "Sale totals before costs", money], ["sold_count", "Cards sold", value => value == null ? "Not estimated" : Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })], ["retained_cost_cents", "Retained inventory cost", money], ["retained_model_value_cents", "Modeled retained value", money]];
  return <div className="pe-result-table-wrap" tabIndex="0" aria-label="Simulation scenario quantiles"><table className="pe-result-table"><thead><tr><th scope="col">Result</th><th scope="col">10th percentile</th><th scope="col">Median</th><th scope="col">90th percentile</th></tr></thead><tbody>{rows.map(([key, label, format]) => <tr key={key}><th scope="row">{label}</th>{["p10", "p50", "p90"].map(q => <td key={q}>{format(metrics[key]?.[q])}</td>)}</tr>)}</tbody></table></div>;
}

function ScenarioResults({ result }) {
  const { metrics, summary, options } = result;
  const release = result.cards?.some(card => (card.effective_price_source || card.price_source) === "release_reference");
  const hasModel = summary.modeled_cards > 0;
  return <div className="pe-results">
    <p className="pe-run-label">{strategies[options.strategy] || "Price scenario"} · {options.horizon_days} days · {options.trials.toLocaleString()} trials · Seed {options.seed}</p>
    <div className="pe-metrics"><Metric label="Median net cash recovered" value={hasModel ? money(metrics.net_cash_cents?.p50) : "Unmodeled"} detail="Cash after selling costs" /><Metric label="Median realized profit / loss" value={hasModel ? money(metrics.realized_profit_cents?.p50) : "Unmodeled"} detail="Sold cards with known purchase cost" /><Metric label="Median cards sold" value={hasModel ? metrics.sold_count?.p50?.toLocaleString(undefined, { maximumFractionDigits: 1 }) ?? "Not estimated" : "Unmodeled"} detail={`${cardCount(summary.modeled_cards)} modeled`} /><Metric label="Median retained cost" value={money(metrics.retained_cost_cents?.p50)} detail="Purchase cost of unsold inventory" /></div>
    <p>{summary.modeled_cards} of {summary.selected_cards} selected cards have a price reference. {summary.unknown_cards} remain unmodeled. {summary.unknown_purchase_cost_cards} have unknown purchase cost.</p>
    <div className="pe-result-notice"><p>These percentiles describe simulated outcomes under the saved assumptions. They are not calibrated confidence intervals.</p><p>Each median summarizes one metric. The medians do not necessarily add up to the same trial's accounting totals.</p><p>Retained inventory value is not cash. Realized profit excludes unsold cards and cards with unknown purchase cost.</p></div>
    {hasModel ? <QuantileTable metrics={metrics} /> : <Notice>No selected card has a price reference. This run preserves known inventory cost. It does not estimate sale outcomes.</Notice>}
    <div className="pe-metrics pe-probabilities"><Metric label="Scenario chance of no modeled sales" value={hasModel ? percent(metrics.probability_no_sale) : "Unmodeled"} /><Metric label="Scenario chance of realized loss" value={hasModel ? percent(metrics.probability_realized_loss_given_known_cost_sale) : "Unmodeled"} detail={metrics.loss_denominator_trials ? `Among ${metrics.loss_denominator_trials.toLocaleString()} trials with a known-cost sale` : "No trial contains a sale with known purchase cost"} /></div>
    <details className="pe-panel"><summary>Assumptions used in this run</summary>
      <dl className="pe-input-values">{settingFields.filter(([key]) => !release || key !== "listing_factor").map(([key, label]) => <React.Fragment key={key}><dt>{label}</dt><dd>{options[key] ?? "Not recorded"}</dd></React.Fragment>)}
        {options.strategy === "bundle" && <><dt>Cards per bundle</dt><dd>{options.bundle_size}</dd><dt>Bundle price fraction</dt><dd>{options.bundle_price_factor}</dd><dt>Bundle 30-day sale chance</dt><dd>{percent(options.bundle_p30)}</dd><dt>Postage per bundle</dt><dd>{money(options.bundle_shipping_cents)}</dd><dt>Packaging per bundle</dt><dd>{money(options.bundle_packaging_cents)}</dd></>}
        {options.strategy === "markdown" && <><dt>Days before reduction</dt><dd>{options.markdown_after_days}</dd><dt>Reduced price fraction</dt><dd>{options.markdown_price_factor}</dd><dt>30-day sale chance after reduction</dt><dd>{percent(options.markdown_p30)}</dd></>}
        {result.costs && <><dt>Sale fee</dt><dd>{feeLabel(result.costs)}</dd><dt>Buyer tax in fee base</dt><dd>{result.costs.tax_percent}%</dd><dt>Fixed order fee</dt><dd>{result.costs.dynamic_fixed ? "$0.30 through a $10 order total; $0.40 above" : money(result.costs.fixed_cents)}</dd><dt>Postage per individual card</dt><dd>{money(result.costs.shipping_cents)}</dd><dt>Packaging per individual card</dt><dd>{money(result.costs.packaging_cents)}</dd></>}
      </dl><ul>{result.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul></details>
    {hasModel && !!result.sensitivity?.length && <details className="pe-panel" open><summary>Price and sale-probability sensitivity</summary><p>This grid uses individual sales and no random price shocks. It shows expected outcomes for alternative input assumptions.</p>{release && <p>The fraction of asks does not affect a release reference. Only the sale-probability assumption changes these rows.</p>}<div className="pe-result-table-wrap" tabIndex="0" aria-label="Price and probability sensitivity"><table className="pe-result-table"><thead><tr><th>Fraction of asks</th><th>30-day sale chance</th><th>Expected cards sold</th><th>Expected net cash</th><th>Expected profit / loss</th><th>Expected retained cost</th></tr></thead><tbody>{result.sensitivity.map((row, index) => <tr key={index}><th scope="row">{percent(row.listing_factor)}</th><td>{percent(row.p30)}</td><td>{row.expected_sold_cards.toFixed(1)}</td><td>{money(row.expected_net_cash_cents)}</td><td>{money(row.expected_realized_profit_cents)}</td><td>{money(row.expected_retained_cost_cents)}</td></tr>)}</tbody></table></div></details>}
    {!!result.cards?.length && <details className="pe-panel"><summary>Per-card scenario results ({result.cards.length})</summary><p>Sale probability is a simulation result under the selected assumptions. Exact duplicate variants share a sold-first price reference.</p><div className="pe-result-table-wrap" tabIndex="0" aria-label="Per-card simulation results"><table className="pe-result-table"><thead><tr><th>Card</th><th>Effective price source</th><th>Chance of sale</th><th>Median price</th><th>Median net cash</th><th>Median profit / loss</th></tr></thead><tbody>{result.cards.map(card => {const source = card.effective_price_source || card.price_source; return <tr key={card.card_id}><th scope="row">{card.label || card.player || card.card_id}</th><td>{sourceNames[source] || "Release reference"}</td><td>{source === "unknown" ? "Unmodeled" : percent(card.sale_probability)}</td><td>{money(card.price_cents?.p50)}</td><td>{source === "unknown" ? "Unmodeled" : money(card.net_cash_cents?.p50)}</td><td>{source === "unknown" ? "Unmodeled" : money(card.realized_profit_cents?.p50)}</td></tr>;})}</tbody></table></div></details>}
  </div>;
}

function RunResults({ run }) {
  return <section className="pe-panel pe-results" aria-label="Saved simulation results"><div className="pe-form-title"><h2>Saved simulation results</h2><a href={`/api/export/simulation/${run.id}`} download>Export run JSON</a></div><p className="pe-subtitle">Saved {new Date(run.created_at).toLocaleString()}. Results use the evidence and assumptions saved with this run.</p><ScenarioResults result={run.result} /></section>;
}

function ReleasePanel({ report, onCompleted, run }) {
  const [busy, setBusy] = React.useState(false), [error, setError] = React.useState(""), [path, setPath] = React.useState("base");
  async function simulate(event) {
    event.preventDefault(); setBusy(true); setError(""); const form = new FormData(event.currentTarget);
    const options = { name: form.get("name"), reference_price_cents: cents(form.get("reference")), purchase_cost_cents: form.get("cost") === "" ? null : cents(form.get("cost")) };
    for (const key of ["quantity", "days_since_release", "horizon_days", "seed", "trials", "low_factor", "base_factor", "high_factor", ...settingFields.filter(([key]) => key !== "listing_factor").map(([key]) => key)]) options[key] = Number(form.get(key));
    try { await onCompleted(await api("/pricing-engine/releases", "POST", options)); }
    catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  const scenarios = run?.result.scenarios || [], active = scenarios.find(item => item.label === path) || scenarios[0];
  return <>
    <section className="pe-panel"><div className="pe-form-title"><h2>New-release sandbox</h2><span className="pe-source active_listing">Unvalidated scenario</span></div><p>Test a single-card release with explicit price paths. This sandbox does not add hypothetical cards to your collection.</p><p>The reference price applies today. Low, base, and high factors describe possible changes over the next time horizon.</p>
      <form onSubmit={simulate}><div className="form-grid">
        <Field label="Player and product" name="name" maxLength="120" placeholder="Name the release or card" required />
        <Field label="Current reference price per card (USD)" name="reference" type="number" min="0.01" max="10000000" step="0.01" required />
        <Field label="Purchase cost per card (USD, optional)" name="cost" type="number" min="0" max="10000000" step="0.01" />
        <Field label="Quantity" name="quantity" type="number" min="1" max="100" step="1" defaultValue="1" required />
        <Field label="Days since release" name="days_since_release" type="number" min="0" max="3650" step="1" defaultValue="0" required />
        <Field label="Future time horizon"><select name="horizon_days" defaultValue="90"><option value="30">30 days</option><option value="90">90 days</option><option value="180">180 days</option></select></Field>
        <Field label="Low price factor" name="low_factor" type="number" min="0" max="5" step="0.01" defaultValue="0.60" required />
        <Field label="Base price factor" name="base_factor" type="number" min="0" max="5" step="0.01" defaultValue="0.85" required />
        <Field label="High price factor" name="high_factor" type="number" min="0" max="5" step="0.01" defaultValue="1.20" required />
        <Field label="Random seed" name="seed" type="number" min="0" max="2147483647" step="1" defaultValue="42" required />
        <Field label="Simulation trials"><select name="trials" defaultValue="10000"><option value="10000">10,000 trials per path</option><option value="1000">1,000 trials per path</option></select></Field>
      </div><p className="pe-subtitle">Example factors: 0.60 means a 40% decline. 1.00 means no change. 1.20 means 20% growth. These are assumptions.</p>
      <details className="pe-panel"><summary>Sale-probability and price variation</summary><div className="form-grid">{settingFields.filter(([key]) => key !== "listing_factor").map(([key, label, fallback, min, max]) => <Field key={key} label={label} name={key} type="number" min={min} max={max} step="0.01" defaultValue={report.settings[key] ?? fallback} required />)}</div></details>
      <button className="primary" disabled={busy}>{busy ? "Running release scenarios..." : "Run and save release scenarios"}</button>{busy && <p role="status">The server is running the three price paths.</p>}{error && <p role="alert" className="error">{error}</p>}
      </form>
    </section>
    {run && <section className="pe-panel pe-results"><div className="pe-form-title"><h2>{run.result.options.name}</h2><a href={`/api/export/simulation/${run.id}`} download>Export release run JSON</a></div><p className="pe-subtitle">Saved {new Date(run.created_at).toLocaleString()}. Release scenarios do not use a fitted historical release model.</p><p>{cardCount(run.result.options.quantity)} · Reference age: {run.result.options.days_since_release} days after release · Purchase cost per card: {money(run.result.options.purchase_cost_cents)}.</p>
      <div className="pe-metrics pe-release-paths">{scenarios.map(item => <Metric key={item.label} label={`${item.label[0].toUpperCase() + item.label.slice(1)} path · factor ${item.future_factor}`} value={money(item.terminal_reference_cents)} detail={`Future reference per card · from ${money(item.reference_price_cents)}`} />)}</div>
      <Field label="Inspect price path"><select value={path} onChange={e => setPath(e.target.value)}>{scenarios.map(item => <option value={item.label} key={item.label}>{item.label[0].toUpperCase() + item.label.slice(1)} path</option>)}</select></Field>
      <details className="pe-panel"><summary>Release model limits</summary><ul>{run.result.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul></details>
      {active && <ScenarioResults result={active.simulation} />}
    </section>}
  </>;
}
function RunHistory({ history, onLoad }) {
  return <section className="pe-panel"><h2>Saved scenario runs</h2><p>Each run stores its data snapshot, input assumptions, seed, and results.</p>{!history.length ? <p>No saved runs yet. Run a collection or release scenario to save one.</p> : <div className="pe-history">{history.map(item => <article key={item.id}><div><h3>{item.type === "release" ? item.options?.name || "New release" : strategies[item.options?.strategy] || "Collection simulation"}</h3><p>{item.type === "release" ? <>Release scenario · {cardCount(item.options?.quantity)}</> : <>{cardCount(item.summary?.selected_cards)} selected · {item.summary?.modeled_cards ?? "Unknown"} modeled · {item.summary?.unknown_cards ?? "Unknown"} unpriced</>}</p><p>{new Date(item.created_at).toLocaleString()} · Seed {item.seed}</p><small>{item.options?.horizon_days ? `${item.options.horizon_days} days · ` : ""}{item.options?.trials || 10000} trials</small></div><button onClick={() => onLoad(item.id)}>Open saved run</button><a href={`/api/export/simulation/${item.id}`} download>JSON</a></article>)}</div>}</section>;
}
