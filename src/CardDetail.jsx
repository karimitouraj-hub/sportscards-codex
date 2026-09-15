import React from "react";
import { api, money, cents, fields } from "./api";
import { Modal, Field, IdentityFields, Notice } from "./ui";
import { AnalysisDetail } from "./Analysis";

export default function CardDetail({ card, state, refresh, onClose, initialTab = "details" }) {
  const [tab, setTab] = React.useState(initialTab),
    [details, setDetails] = React.useState(card),
    [analysis, setAnalysis] = React.useState(null),
    [error, setError] = React.useState(""),
    [saved, setSaved] = React.useState(false),
    [busy, setBusy] = React.useState(false);
  React.useEffect(() => {
    let cancelled = false;
    api("/cards/" + card.id + "/analysis")
      .then((a) => {
        if (!cancelled) setAnalysis(a);
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      });
    return () => {
      cancelled = true;
    };
  }, [card.id, card.revision, state.comparables.length, state.allocations]);
  React.useEffect(() => setDetails(card), [card.id, card.revision]);
  async function act(fn) {
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      await fn();
      await refresh();
      setAnalysis(await api("/cards/" + card.id + "/analysis"));
      setSaved(true);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const observations = state.observations.filter((o) => o.card_id === card.id)
    .sort((a, b) => Number(b.id === card.primary_observation_id) - Number(a.id === card.primary_observation_id));
  return (
    <Modal title={card.player} wide onClose={onClose}>
      <div className="detail-meta">
        {[card.year, card.set, card.number && "#" + card.number]
          .filter(Boolean)
          .join(" · ")}
        <span>Physical card {card.id.slice(0, 8)}</span>
      </div>
      <nav className="tabs" aria-label="Card details">
        {["details", "purchase", "valuation"].map((t) => (
          <button
            className={tab === t ? "active" : ""}
            onClick={() => setTab(t)}
            key={t}
          >
            {t === "details"
              ? "Card details"
              : t === "purchase"
                ? "Purchase match"
                : "Value & evidence"}
          </button>
        ))}
      </nav>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {saved && (
        <p role="status" className="save-status">
          Saved. Evidence and estimates are current.
        </p>
      )}
      {tab === "details" ? (
        <div className="review-dialog">
          <div className="card-images">
            {observations.map((o) => (
              <figure key={o.id}>
                <img
                  src={"/media/crop/" + o.id + "?v=" + (o.crop_revision || 0)}
                  alt={o.side + " observation of " + card.player}
                />
                <figcaption>
                  {o.side} ·{" "}
                  <a href={"/media/original/" + o.photo_id}>Original photo</a>
                  {o.id !== card.primary_observation_id && <button className="text-link" type="button" disabled={busy}
                    onClick={() => act(() => api("/cards/" + card.id, "PATCH", { revision: card.revision, primary_observation_id: o.id }))}>
                    Use as cover
                  </button>}
                </figcaption>
              </figure>
            ))}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              act(() => api("/cards/" + card.id, "PATCH", details));
            }}
          >
            <IdentityFields value={details} onChange={setDetails} />
            <Field label="Visible features" value={details.visual_description || ""} maxLength={500}
              onChange={(e) => setDetails({ ...details, visual_description: e.target.value })} />
            <Field label="Printed serial number" value={details.serial_number || ""} maxLength={100}
              onChange={(e) => setDetails({ ...details, serial_number: e.target.value })} />
            <Field label="Notes">
              <textarea
                rows={3}
                value={details.notes || ""}
                onChange={(e) =>
                  setDetails({ ...details, notes: e.target.value })
                }
              />
            </Field>
            <p className="muted">
              {card.evidence_state === "photo_reviewed" ? "Photo reviewed" : "User confirmed"} · Revision {card.revision}. Changes recalculate
              purchase suggestions and valuation.
            </p>
            {card.evidence_state === "photo_reviewed" && <Notice>
              These details come from a photo review. Blank fields remain unknown. Visible colors do not establish an exact parallel or condition.
            </Notice>}
            <div className="actions">
              <button className="primary" disabled={busy}>
                Save card details
              </button>
            </div>
          </form>
        </div>
      ) : tab === "purchase" ? (
        <PurchaseMatch
          card={card}
          state={state}
          analysis={analysis}
          act={act}
          busy={busy}
        />
      ) : (
        <Valuation
          card={card}
          state={state}
          analysis={analysis}
          act={act}
          busy={busy}
        />
      )}
    </Modal>
  );
}
function PurchaseMatch({ card, state, analysis, act, busy }) {
  const [purchase, setPurchase] = React.useState("");
  const allocation = state.allocations.find((a) => a.card_id === card.id);
  const suggestions = analysis?.purchases || [];
  function submit(e) {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.currentTarget));
    act(() =>
      api("/cards/" + card.id + "/allocation", "POST", {
        purchase_id: purchase,
        cost_cents: cents(data.cost),
        basis: data.basis,
      }),
    );
  }
  return (
    <>
      <Notice>
        Suggestions compare text only. Confirm the exact variant and physical
        card. Lot cost allocations remain Estimated.
      </Notice>
      {allocation && (
        <div className="evidence-summary">
          <strong>Allocated cost: {money(allocation.cost_cents)}</strong>
          <p>
            {
              state.purchases.find((p) => p.id === allocation.purchase_id)
                ?.title
            }
          </p>
          <small>{allocation.basis}</small>
        </div>
      )}
      {suggestions.length > 0 && (
        <div className="suggestions">
          <h3>Suggested purchase lines</h3>
          {suggestions.map((s) => (
            <button
              key={s.purchase_id}
              onClick={() => setPurchase(s.purchase_id)}
            >
              {s.title}
              <small>{s.score} matching fields · Review required</small>
            </button>
          ))}
        </div>
      )}
      {state.purchases.length ? (
        <form onSubmit={submit}>
          <div className="form-grid">
            <Field label="Purchase line">
              <select
                required
                value={purchase}
                onChange={(e) => setPurchase(e.target.value)}
              >
                <option value="">Select a purchase</option>
                {state.purchases
                  .filter((p) => !["cancelled", "refunded"].includes(p.status))
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.title} · {money(p.total_cents - p.refund_cents)}
                    </option>
                  ))}
              </select>
            </Field>
            <Field
              label="Cost allocated to this card (USD)"
              type="number"
              min="0"
              step="0.01"
              name="cost"
              required
              defaultValue={
                allocation ? allocation.cost_cents / 100 : undefined
              }
            />
            <Field
              label="Allocation basis"
              name="basis"
              required
              placeholder="For example: equal share of a four-card lot"
              defaultValue={allocation?.basis}
            />
          </div>
          <div className="actions">
            <button className="primary" disabled={busy}>
              Save cost allocation
            </button>
          </div>
        </form>
      ) : (
        <p>Add a record in Purchases before you allocate a cost.</p>
      )}
    </>
  );
}
function Valuation({ card, state, analysis, act, busy }) {
  const [adding, setAdding] = React.useState(false),
    [comp, setComp] = React.useState(
      Object.fromEntries(fields.map((k) => [k, card[k] || ""])),
    );
  const value = analysis?.valuation;
  const comps = state.comparables.filter((c) => c.card_id === card.id);
  function saveFees(e) {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.currentTarget));
    act(() =>
      api("/cards/" + card.id, "PATCH", {
        revision: card.revision,
        fees: {
          percent: Number(data.percent),
          fixed_cents: cents(data.fixed),
          shipping_cents: cents(data.shipping),
        },
      }),
    );
  }
  function saveComp(e) {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.currentTarget));
    act(() =>
      api("/cards/" + card.id + "/comparables", "POST", {
        ...comp,
        ...data,
        price_cents: cents(data.price),
        shipping_cents: cents(data.shipping),
        currency: "USD",
      }),
    );
  }
  if (!value) return <p role="status">Loading evidence...</p>;
  if (value.version) return <><AnalysisDetail value={value} card={card} state={state} /><ReviewedEvidenceForm card={card} act={act} busy={busy} /></>;
  return (
    <>
      <Notice>
        Estimates use at least three distinct matching sold sources from the
        past 90 days. Asking prices stay separate.
      </Notice>
      <div className="value-stats">
        <div>
          <small>Estimated market value</small>
          <strong>{money(value?.market_value_cents)}</strong>
        </div>
        <div>
          <small>Estimated net proceeds</small>
          <strong>{money(value?.net_proceeds_cents)}</strong>
        </div>
        <div>
          <small>Estimated profit</small>
          <strong>{money(value?.profit_cents)}</strong>
        </div>
      </div>
      <p>{value?.recommendation || "Loading evidence…"}</p>
      {value?.range_cents && (
        <p className="muted">
          Observed range: {money(value.range_cents[0])}–
          {money(value.range_cents[1])}. Includes comparable shipping.
        </p>
      )}
      <details>
        <summary>Set selling cost assumptions</summary>
        <form onSubmit={saveFees}>
          <div className="form-grid">
            <Field
              label="Fee (%)"
              type="number"
              name="percent"
              min="0"
              max="100"
              step="0.01"
              defaultValue={card.fees?.percent ?? ""}
              required
            />
            <Field
              label="Fixed fee (USD)"
              type="number"
              name="fixed"
              min="0"
              step="0.01"
              defaultValue={card.fees ? card.fees.fixed_cents / 100 : ""}
              required
            />
            <Field
              label="Shipping cost (USD)"
              type="number"
              name="shipping"
              min="0"
              step="0.01"
              defaultValue={card.fees ? card.fees.shipping_cents / 100 : ""}
              required
            />
          </div>
          <button disabled={busy}>Save cost assumptions</button>
        </form>
      </details>
      <div className="section-header">
        <h3>Comparable evidence</h3>
        <button onClick={() => setAdding(!adding)}>
          {adding ? "Close evidence form" : "Add comparable"}
        </button>
      </div>
      {adding && (
        <form onSubmit={saveComp} className="evidence-form">
          <IdentityFields value={comp} onChange={setComp} />
          <div className="form-grid">
            <Field label="Source URL" name="source_url" type="url" required />
            <Field label="Sale status">
              <select name="status">
                <option value="sold">Sold</option>
                <option value="asking">Asking price</option>
                <option value="unknown">Unknown</option>
              </select>
            </Field>
            <Field label="Sale date" name="sold_date" type="date" required />
            <Field
              label="Price (USD)"
              name="price"
              type="number"
              min="0.01"
              step="0.01"
              required
            />
            <Field
              label="Buyer shipping (USD)"
              name="shipping"
              type="number"
              min="0"
              step="0.01"
              defaultValue="0"
              required
            />
          </div>
          <p className="muted">
            Confirm each field against the source. This record is user-entered
            evidence.
          </p>
          <button className="primary" disabled={busy}>
            Save comparable
          </button>
        </form>
      )}
      {comps.length ? (
        comps.map((c) => {
          const excluded = value?.excluded.find((x) => x.id === c.id);
          return (
            <article className="comparable-row" key={c.id}>
              <div>
                <a href={c.source_url} target="_blank" rel="noreferrer">
                  View source
                </a>
                <p>
                  {c.sold_date} · {c.status} · {c.variant} · {c.grade}
                </p>
                <small>
                  {excluded
                    ? excluded.reasons.join(" ")
                    : "Included · User-entered evidence"}
                </small>
              </div>
              <strong>{money(c.price_cents + c.shipping_cents)}</strong>
            </article>
          );
        })
      ) : (
        <p className="muted">
          No comparable evidence. The value remains unknown.
        </p>
      )}
    </>
  );
}

function ReviewedEvidenceForm({card, act, busy}) {
  function submit(e) {
    e.preventDefault(); const d=Object.fromEntries(new FormData(e.currentTarget));
    act(()=>api('/cards/'+card.id+'/comparables','POST',{
      ...Object.fromEntries(fields.map(k=>[k,card[k]||''])), source_url:d.source, source_title:d.title,
      sold_date:d.date, status:'sold', currency:'USD', price_cents:cents(d.price), shipping_cents:cents(d.shipping),
      match_reviewed:true, shipping_known:true, price_status:'known', evidence_state:'user_entered',
      match_note:d.note, condition_evidence:'User reviewed the raw card and sale evidence.'
    }));
  }
  return <details><summary>Add a reviewed sold transaction</summary><form onSubmit={submit} className="evidence-form">
    <p>Compare the player, year, insert, variant, print run, grade, and condition. Use the actual sold amount. Hidden accepted offers do not qualify.</p>
    <div className="form-grid"><Field label="Source URL" name="source" type="url" required/><Field label="Listing title" name="title" required/><Field label="Sale date" name="date" type="date" required/><Field label="Sold price (USD)" name="price" type="number" min="0.01" step="0.01" required/><Field label="Buyer shipping (USD)" name="shipping" type="number" min="0" step="0.01" required/><Field label="Why this exact card matches" name="note" required/></div>
    <label className="check"><input type="checkbox" required/> I verified the exact card, sold amount, and shipping cost.</label><button className="primary" disabled={busy}>Save reviewed sale</button>
  </form></details>;
}
