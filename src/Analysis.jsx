import React from "react";
import { api, money, cents } from "./api";
import { Field, Notice } from "./ui";

const categories = {hold: "Hold", sell_now: "Sell now", patient_sale: "Patient sale", bundle: "Bulk, bundle, or donate", discard_candidate: "Discard candidate", needs_evidence: "Needs more evidence"};

export function AnalysisDetail({ value, card, state }) {
  if (!value) return <p>Loading analysis...</p>;
  const allocations = state.allocations.filter(a => a.card_id === card.id);
  const included = new Set(value.included);
  const comps = state.comparables.filter(c => included.has(c.id));
  return <div className="analysis-detail">
    <span className={"decision " + value.category}>{value.category_label}</span>
    <p>{value.recommendation}</p>
    <div className="value-stats">
      <div><small>Purchase cost</small><strong>{money(value.purchase_cost_cents)}</strong></div>
      <div><small>Estimated sale total</small><strong>{money(value.market_value_cents)}</strong></div>
      <div><small>Estimated net proceeds</small><strong>{money(value.net_proceeds_cents)}</strong></div>
      <div><small>Estimated profit / loss</small><strong>{money(value.profit_cents)}</strong></div>
    </div>
    <p><strong>{value.sample_count} recent sold transactions</strong> · {value.confidence} confidence. {value.range_cents && <>Observed totals: {money(value.range_cents[0])} to {money(value.range_cents[1])}.</>} Sale totals include buyer shipping.</p>
    <p>Estimated break-even sale total: <strong>{money(value.break_even_cents)}</strong>. This covers the allocated purchase cost and selected selling costs.</p>
    <dl className="decision-notes"><dt>Time horizon</dt><dd>{value.horizon}</dd><dt>Reconsider when</dt><dd>{value.trigger}</dd></dl>
    <details><summary>Costs and uncertainty</summary>
      <p>{value.costs.fee_model === "ebay_us_non_store" ? "Fee: 13.25% through $7,500 per sold item, then 2.35% on the excess." : `Custom fee assumption: ${value.costs.percent}% of the full sale total.`} The fee base includes buyer shipping and estimated tax. Fixed fee: $0.30 through $10, or $0.40 above $10.</p>
      <p>Assumptions: {value.costs.tax_percent}% buyer tax, {money(value.costs.shipping_cents)} postage, and {money(value.costs.packaging_cents)} packaging. Change these on the Analysis page.</p>
      <a href={value.costs.source_url} target="_blank" rel="noreferrer">eBay fee source</a>
      <ul>{value.uncertainty.map(t => <li key={t}>{t}</li>)}</ul>
    </details>
    <h3>Purchase evidence</h3>
    {card.purchase_match_note && <p className="muted">{card.purchase_match_note}</p>}
    {allocations.map(a => {const p = state.purchases.find(p => p.id === a.purchase_id); return <article className="comparable-row" key={a.id}><div><a href={p?.source_ref} target="_blank" rel="noreferrer">{p?.title}</a><p>{p?.order_date} · Account {p?.account}</p><small>{a.basis}</small></div><strong>{money(a.cost_cents)}</strong></article>;})}
    {!allocations.length && <p>No purchase has been matched.</p>}
    <h3>Sold evidence used</h3>
    {comps.map(c => <article className="comparable-row" key={c.id}><div><a href={c.source_url} target="_blank" rel="noreferrer">{c.source_title || "Sold listing"}</a><p>Sold {c.sold_date} · Retrieved {c.retrieved_at?.slice(0,10)}</p><small>{c.match_note}</small></div><strong>{money(c.price_cents + c.shipping_cents)}</strong></article>)}
    {!comps.length && <p>No recent exact-variant sale with a visible price qualifies. The value remains unknown.</p>}
    {!!value.excluded.length && <details><summary>{value.excluded.length} excluded records</summary>{value.excluded.map(e => <p key={e.id}>{e.reasons.join(" ")}</p>)}</details>}
    {value.research?.reviewed_at && <details><summary>Research record</summary><p>Reviewed {value.research.reviewed_at.slice(0,10)}. Query: {value.research.query}</p><p>{value.research.limitations}</p>{value.research.sources?.map(s => <p key={s.url}><a href={s.url} target="_blank" rel="noreferrer">{s.label}</a></p>)}</details>}
  </div>;
}

export default function Analysis({ state, onCard, refresh }) {
  const [report, setReport] = React.useState(null), [error, setError] = React.useState(""), [query, setQuery] = React.useState(""), [filter, setFilter] = React.useState("all"), [sort, setSort] = React.useState("cost"), [saved, setSaved] = React.useState(false);
  React.useEffect(() => {let current = true; api("/portfolio").then(r => {if (current) setReport(r);}).catch(e => {if(current) setError(e.message);}); return () => {current = false;};}, [state]);
  async function saveCosts(e) {e.preventDefault(); setError(""); setSaved(false); const d = Object.fromEntries(new FormData(e.currentTarget)); try {await api("/analysis-settings", "PATCH", {percent:Number(d.percent), tax_percent:Number(d.tax), shipping_cents:cents(d.shipping), packaging_cents:cents(d.packaging)}); await refresh(); setSaved(true);} catch(e) {setError(e.message);}}
  if (!report) return <p role="status">{error || "Loading purchase and sales analysis..."}</p>;
  const summary = report.summary;
  const rows = report.rows.map(r => ({...r, card:state.cards.find(c => c.id === r.card_id)})).filter(r => r.card && [r.card.player,r.card.set,r.card.variant,r.card.serial_number].join(" ").toLowerCase().includes(query.toLowerCase())).filter(r => filter === "all" || r.category === filter).sort((a,b) => sort === "name" ? a.card.player.localeCompare(b.card.player) : (b[sort === "cost" ? "purchase_cost_cents" : sort === "value" ? "market_value_cents" : "profit_cents"] ?? -Infinity) - (a[sort === "cost" ? "purchase_cost_cents" : sort === "value" ? "market_value_cents" : "profit_cents"] ?? -Infinity));
  return <>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="analysis-stats">
      <div><small>Cost of matched photo cards</small><strong>{money(summary.purchase_cost_cents)}</strong><span>{summary.matched} of {summary.cards} matched</span></div>
      <div><small>Estimated sale totals</small><strong>{money(summary.market_value_cents)}</strong><span>{summary.valued} of {summary.cards} have sold evidence</span></div>
      <div><small>Estimated net proceeds</small><strong>{money(summary.net_proceeds_cents)}</strong><span>After fees, postage, and packaging</span></div>
      <div><small>Estimated profit / loss</small><strong>{money(summary.profit_cents)}</strong><span>Only cards with both cost and value</span></div>
    </div>
    <Notice>{summary.unvalued} cards have no supported current value. Estimated totals cover {summary.valued} valued cards only. Those cards cost {money(summary.valued_purchase_cost_cents)}. Unknown values are not zero. Purchase records can include cards outside this collection.</Notice>
    <p className="muted">Net proceeds assume one shipment per card. Bundling cards can reduce postage. These estimates do not predict future appreciation.</p>
    <p className="muted">{state.photos.length} photos uploaded · {state.observations.length} card views · {state.cards.length} physical cards · {summary.matched} purchases matched · {summary.researched} research reviews · {summary.valued} with sold evidence</p>
    <details className="cost-settings"><summary>Selling cost assumptions</summary><p>{report.costs.basis} Confirm envelope eligibility before using lower postage for a thin, low-value card.</p><form onSubmit={saveCosts}><div className="form-grid">
      <Field label="Fee (%)" name="percent" type="number" min="0" max="50" step="0.01" defaultValue={report.costs.percent} required />
      <Field label="Buyer tax assumption (%)" name="tax" type="number" min="0" max="50" step="0.01" defaultValue={report.costs.tax_percent} required />
      <Field label="Postage per card (USD)" name="shipping" type="number" min="0" step="0.01" defaultValue={report.costs.shipping_cents/100} required />
      <Field label="Packaging per card (USD)" name="packaging" type="number" min="0" step="0.01" defaultValue={report.costs.packaging_cents/100} required />
    </div><button>Save selling costs</button>{saved && <p role="status">Selling costs saved. Estimates recalculated.</p>}</form><p><a href={report.costs.source_url} target="_blank" rel="noreferrer">Current eBay fee source</a></p></details>
    <div className="toolbar analysis-toolbar"><input aria-label="Search analysis" placeholder="Search player, set, or serial" value={query} onChange={e => setQuery(e.target.value)} /><select aria-label="Recommendation filter" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All recommendations</option>{Object.entries(categories).map(([k,v]) => <option value={k} key={k}>{v}</option>)}</select><select aria-label="Sort analysis" value={sort} onChange={e => setSort(e.target.value)}><option value="cost">Highest purchase cost</option><option value="value">Highest estimated value</option><option value="profit">Highest estimated profit</option><option value="name">Player name</option></select></div>
    <div className="analysis-export"><span>{rows.length} cards shown</span><a href="/api/export/analysis-csv" download>Analysis CSV</a><a href="/api/export/json" download>JSON with evidence</a></div>
    <div className="analysis-list">{rows.map(r => {const c=r.card; const obs = state.observations.find(o=>o.id === c.primary_observation_id) || state.observations.find(o=>o.card_id===c.id); return <button className="analysis-row" key={c.id} onClick={() => onCard(c)}>
      {obs && <img src={"/media/crop/"+obs.id+"?v="+(obs.crop_revision||0)} alt={c.player+" card"} loading="lazy" />}
      <div className="analysis-card-name"><h3>{c.player}</h3><p>{[c.year,c.set,c.variant].filter(Boolean).join(" · ")}</p><small>{c.serial_number && "Serial "+c.serial_number+" · "}{r.sample_count} sold · {r.confidence}</small><span className={"decision "+r.category}>{r.category_label}</span></div>
      <div className="analysis-numbers"><span>Paid<strong>{money(r.purchase_cost_cents)}</strong></span><span>Est. sale<strong>{money(r.market_value_cents)}</strong></span><span>Est. net<strong>{money(r.net_proceeds_cents)}</strong></span><span>Est. profit<strong>{money(r.profit_cents)}</strong></span></div>
    </button>;})}</div>{!rows.length && <p>No cards match this filter.</p>}
  </>;
}
