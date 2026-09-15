import React from "react";
import { Check, Copy, Download, RefreshCw, ArrowUpRight } from "lucide-react";
import { api, money } from "./api";
import "./selling-prep.css";

const sellerLabels = {
  purchase_cost_cents: "Purchase cost",
  modeled_net_at_bin_cents: "Estimated net at item price",
  modeled_profit_at_bin_cents: "Estimated profit at item price",
  modeled_net_at_minimum_offer_cents: "Estimated net at offer guide",
  modeled_profit_at_minimum_offer_cents: "Estimated profit at offer guide",
  modeled_net_at_starting_bid_cents: "Estimated net at starting bid",
  modeled_profit_at_starting_bid_cents: "Estimated profit at starting bid",
  cost_recovery_item_cents: "Estimated item price to recover cost",
};

function CopyField({ label, value, multiline = false }) {
  const field = React.useRef(null);
  const [message, setMessage] = React.useState("");
  async function copy() {
    try {
      if (window.isSecureContext && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        setMessage("Copied");
        return;
      }
    } catch { /* The selected text below remains available on HTTP and older browsers. */ }
    field.current.focus();
    field.current.select();
    field.current.setSelectionRange(0, value.length);
    try {
      setMessage(document.execCommand("copy") ? "Copied" : "Text selected. Use your device’s Copy command.");
    } catch {
      setMessage("Text selected. Use your device’s Copy command.");
    }
  }
  return <div className="sp-copy-field">
    <div className="sp-field-heading"><label>{label}</label><button type="button" onClick={copy}><Copy size={15} />Copy {label.toLowerCase()}</button></div>
    <textarea ref={field} aria-label={label} value={value} readOnly rows={multiline ? 7 : 2} />
    <span className="sp-copy-status" role="status">{message}</span>
  </div>;
}

function Draft({ draft, onCard }) {
  const isAuction = draft.listing_format === "auction";
  const duration = Number.isInteger(draft.duration_days) ? `${draft.duration_days} ${draft.duration_days === 1 ? "day" : "days"}` : "Duration needs review";
  return <article className="sp-draft">
    <div className="sp-draft-heading">
      <div><span className={`sp-status ${draft.ready ? "ready" : "review"}`}>{draft.ready ? <Check size={15} /> : null}{draft.ready ? "Ready to copy" : "Needs review"}</span><h2>{draft.title || "Untitled draft"}</h2>{isAuction ? <p className="sp-auction-format">Auction · {duration} · {draft.reserve_price_cents == null ? "No reserve" : "Reserve needs review"}</p> : null}</div>
      <button onClick={() => onCard?.({ id: draft.card_id })}>View card<ArrowUpRight size={16} /></button>
    </div>
    {draft.blockers.length > 0 ? <div className="sp-blockers" role="note"><strong>Complete this draft</strong><ul>{draft.blockers.map(note => <li key={note}>{note}</li>)}</ul></div> : null}
    <div className="sp-draft-body">
      <div className="sp-photo-pair">
        {["front", "back"].map(side => {
          const photo = draft.photos.find(item => item.side === side);
          return <figure key={side}>{photo ? <><a href={photo.url} target="_blank" rel="noreferrer"><img src={photo.url} alt={`${side === "front" ? "Front" : "Back"} of ${draft.title}`} loading="lazy" /></a><figcaption>{side === "front" ? "Front" : "Back"}<a href={photo.download_url}><Download size={14} />Download</a></figcaption></> : <div className="sp-missing-photo">{side === "front" ? "Front" : "Back"} photo needed</div>}</figure>;
        })}
      </div>
      <div className="sp-draft-content">
        {isAuction ? <p className="sp-auction-note">The final bid is unknown.</p> : null}
        <div className="sp-prices"><div><span>{isAuction ? "Starting bid" : "Item price"}</span><strong>{money(draft.price_cents)}</strong></div><div><span>Buyer shipping</span><strong>{money(draft.shipping_cents)}</strong></div><div><span>{isAuction ? "Starting bid + shipping" : "Total before buyer tax"}</span><strong>{money(draft.price_cents == null || draft.shipping_cents == null ? null : draft.price_cents + draft.shipping_cents)}</strong></div></div>
        <CopyField label="Title" value={draft.title} />
        <CopyField label="Description" value={draft.description} multiline />
        <div className="sp-condition"><strong>Condition</strong><p>{draft.condition || "Needs review"}</p></div>
        <details className="sp-specifics"><summary>Item specifics <span>{Object.keys(draft.specifics).length} fields</span></summary><dl>{Object.entries(draft.specifics).map(([key, value]) => <React.Fragment key={key}><dt>{key}</dt><dd>{value}</dd></React.Fragment>)}</dl></details>
        <div className="sp-seller-notes"><strong>Seller guidance</strong>{isAuction ? null : <p>Manual offer guide: <b>{draft.minimum_offer_cents == null ? "Not set" : money(draft.minimum_offer_cents)}</b> for the item, plus buyer shipping. This is a pricing guide. It does not set an automatic offer rule.</p>}{draft.pricing_note ? <p>{draft.pricing_note}</p> : null}{Object.keys(draft.seller_analysis || {}).length ? <><dl className="sp-seller-analysis">{Object.entries(draft.seller_analysis).map(([key, value]) => <React.Fragment key={key}><dt>{isAuction && key === "cost_recovery_item_cents" ? "Estimated bid to recover cost" : sellerLabels[key] || key}</dt><dd className={value < 0 ? "sp-negative" : ""}>{money(value)}</dd></React.Fragment>)}</dl><p>Estimated profit includes purchase cost. Estimated net does not subtract purchase cost.</p></> : null}{draft.review_notes.length ? <ul>{draft.review_notes.map((note, index) => <li key={index}>{note}</li>)}</ul> : null}<small>Seller guidance stays out of the downloadable listing text.</small></div>
      </div>
    </div>
  </article>;
}

export default function SellingPrep({ onCard }) {
  const [report, setReport] = React.useState(null);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [filter, setFilter] = React.useState("all");
  const [query, setQuery] = React.useState("");
  const refresh = React.useCallback(async () => {
    setLoading(true);
    try { setReport(await api("/listing-prep")); setError(""); }
    catch (failure) { setError(failure.message); }
    finally { setLoading(false); }
  }, []);
  React.useEffect(() => { let cancelled = false; api("/listing-prep").then(data => { if (!cancelled) { setReport(data); setError(""); } }).catch(failure => { if (!cancelled) setError(failure.message); }).finally(() => { if (!cancelled) setLoading(false); }); return () => { cancelled = true; }; }, []);
  const drafts = (report?.drafts || []).filter(draft => (filter === "all" || (filter === "ready" ? draft.ready : !draft.ready)) && `${draft.title} ${draft.description}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="selling-prep">
    <div className="sp-intro"><div><h2>Your listing drafts</h2><p>Review the text and photos, then copy a draft or download the package.</p><p className="muted">These drafts do not publish listings.</p></div><div className="sp-actions">{report?.photo_gallery_url ? <a href={report.photo_gallery_url}>View all photos<ArrowUpRight size={17} /></a> : null}<button onClick={refresh} disabled={loading}><RefreshCw size={17} />Refresh drafts</button>{report?.summary.ready > 0 ? <a className="primary" href={report.package_url}><Download size={18} />Download {report.summary.ready} ready drafts</a> : null}</div></div>
    {error ? <div className="error banner" role="alert">{error}</div> : null}
    {report ? <>
      <div className="sp-summary"><span><strong>{report.summary.drafts}</strong> prepared</span><span><strong>{report.summary.ready}</strong> ready to copy</span><span><strong>{report.summary.needs_review}</strong> need review</span>{report.created_at ? <small>Prepared {new Date(report.created_at).toLocaleDateString()}</small> : null}</div>
      {report.drafts.length ? <><div className="sp-toolbar"><input type="search" aria-label="Search listing drafts" placeholder="Search listing drafts" value={query} onChange={event => setQuery(event.target.value)} /><select aria-label="Filter listing drafts" value={filter} onChange={event => setFilter(event.target.value)}><option value="all">All drafts</option><option value="ready">Ready to copy</option><option value="review">Needs review</option></select></div><div className="sp-drafts">{drafts.map(draft => <Draft key={draft.card_id} draft={draft} onCard={onCard} />)}{drafts.length === 0 ? <p className="sp-empty">No drafts match this search.</p> : null}</div></> : <div className="empty"><h2>No listing batch is prepared yet</h2><p>Prepared drafts will appear here with their linked front and back photos.</p></div>}
    </> : loading ? <p role="status">Loading listing drafts…</p> : null}
  </section>;
}
