import React from "react";
import { api, money, cents } from "./api";
import { Field, Modal, Notice } from "./ui";

export default function Purchases({ state, refresh }) {
  const [open, setOpen] = React.useState(false),
    [error, setError] = React.useState(""),
    [busy, setBusy] = React.useState(false),
    [query, setQuery] = React.useState(""),
    [filter, setFilter] = React.useState("all");
  const shown = state.purchases.filter(p => (p.title+" "+p.account+" "+p.order_id).toLowerCase().includes(query.toLowerCase())).filter(p => filter === "all" || (filter === "refunded" ? p.status === "refunded" : filter === "matched" ? state.allocations.some(a => a.purchase_id === p.id) : !state.allocations.some(a => a.purchase_id === p.id)));
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const data = Object.fromEntries(new FormData(e.currentTarget));
    try {
      await api("/purchases", "POST", {
        ...data,
        quantity: Number(data.quantity),
        total_cents: cents(data.total),
        refund_cents: cents(data.refund),
      });
      await refresh();
      setOpen(false);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="section-header">
        <p>Keep purchase evidence and allocate each lot cost once.</p>
        <button
          className="primary"
          onClick={() => {
            setError("");
            setOpen(true);
          }}
        >
          Add purchase
        </button>
      </div>
      <Notice>
        Purchase evidence can come from reviewed eBay orders or manual records.
        Automatic eBay synchronization is not enabled.
      </Notice>
      {!!state.purchases.length && <p>Imported accounts: {[...new Set(state.purchases.map(p=>p.account))].join(", ")}. {state.purchases.length} purchase lines. Net history cost: {money(state.purchases.reduce((sum,p)=>sum+p.total_cents-p.refund_cents,0))}. This includes cards outside the uploaded photos.</p>}
      <div className="toolbar"><input aria-label="Search purchases" placeholder="Search purchase title or order" value={query} onChange={e=>setQuery(e.target.value)} /><select aria-label="Filter purchases" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">All purchase lines</option><option value="matched">Matched to photo cards</option><option value="unmatched">No photo match</option><option value="refunded">Refunded</option></select></div>
      <p className="muted">{shown.length} purchase lines shown</p>
      {state.purchases.length ? (
        <div className="purchase-list">
          {shown.map((p) => {
            const allocations = state.allocations.filter(
              (a) => a.purchase_id === p.id,
            );
            return (
              <article className="purchase-row" key={p.id}>
                <div>
                  <h3>{p.title}</h3>
                  <p>
                    {p.account} · {/^(https?:\/\/)/.test(p.source_ref) ? <a href={p.source_ref} target="_blank" rel="noreferrer">View purchase listing</a> : p.source_ref}
                  </p>
                  <small>
                    {p.status} · {p.quantity} cards · {allocations.length}{" "}
                    allocated
                  </small>
                  {p.condition && <p>Purchase condition: {p.condition}</p>}
                  {p.order_date && <small>Ordered {p.order_date} · {p.order_id}</small>}
                  {p.cost_basis && <p>{p.cost_basis}</p>}
                  {p.evidence_state === "browser_observed" && <small>Read from eBay purchase history</small>}
                </div>
                <div className="amount">
                  <strong>{money(p.total_cents - p.refund_cents)}</strong>
                  <small>
                    {p.refund_cents
                      ? money(p.refund_cents) + " refunded"
                      : "Total cost"}
                  </small>
                  <small>
                    {money(
                      p.total_cents -
                        p.refund_cents -
                        allocations.reduce((s, a) => s + a.cost_cents, 0),
                    )}{" "}
                    unallocated
                  </small>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty compact">
          <h2>No purchase records yet</h2>
          <p>Add a purchase line from an order, receipt, or other source.</p>
        </div>
      )}
      {open && (
        <Modal title="Add purchase evidence" onClose={() => setOpen(false)}>
          <form onSubmit={submit}>
            <div className="form-grid">
              <Field
                label="Purchase title"
                name="title"
                required
                maxLength={1000}
              />
              <Field
                label="Account label"
                name="account"
                required
                placeholder="Account name or manual source"
              />
              <Field
                label="Order or receipt line reference"
                name="source_ref"
                required
              />
              <Field
                label="Quantity of physical cards"
                name="quantity"
                type="number"
                min="1"
                max="10000"
                defaultValue="1"
                required
              />
              <Field
                label="Total cost including shipping and tax (USD)"
                name="total"
                type="number"
                min="0"
                step="0.01"
                required
              />
              <Field
                label="Refund (USD)"
                name="refund"
                type="number"
                min="0"
                step="0.01"
                defaultValue="0"
                required
              />
              <Field label="Purchase status">
                <select name="status">
                  <option value="completed">Completed</option>
                  <option value="cancelled">Cancelled</option>
                  <option value="refunded">Refunded</option>
                </select>
              </Field>
              <Field
                label="Condition from the purchase source"
                name="condition"
                placeholder="User-provided purchase condition"
              />
            </div>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            <div className="actions">
              <button className="primary" disabled={busy}>
                Save purchase
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}
