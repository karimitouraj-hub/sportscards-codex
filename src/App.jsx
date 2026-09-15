import React from "react";
import { Image, ShoppingCart, Smartphone, Upload, X, ChartNoAxesCombined, SlidersHorizontal, ClipboardList } from "lucide-react";
import { api } from "./api";
import { CardMark } from "./ui";
import Collection from "./Collection";
import PhotoInbox from "./PhotoInbox";
import Purchases from "./Purchases";
import UploadDialog from "./UploadDialog";
import CardDetail from "./CardDetail";
import Analysis from "./Analysis";
import PricingEngine from "./PricingEngine";
import SellingPrep from "./SellingPrep";

const empty = {
  cards: [],
  photos: [],
  observations: [],
  purchases: [],
  allocations: [],
  comparables: [],
  jobs: [],
};
export default function App() {
  const [state, setState] = React.useState(empty),
    [view, setView] = React.useState("analysis"),
    [uploading, setUploading] = React.useState(false),
    [selected, setSelected] = React.useState(null),
    [message, setMessage] = React.useState(""),
    [loaded, setLoaded] = React.useState(false);
  const refresh = React.useCallback(async () => {
    const data = await api("/state");
    setState(data);
    setLoaded(true);
  }, []);
  React.useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await api("/state");
        if (!cancelled) {
          setState(data);
          setLoaded(true);
        }
      } catch (e) {
        if (!cancelled) setMessage(e.message);
      }
    }
    poll();
    const timer = setInterval(poll, 4000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);
  const needReview = state.photos.filter((p) => !p.review_complete).length;
  const card = state.cards.find((c) => c.id === selected);
  const titles = {
    analysis: ["Collection analysis", "What you paid. What the sold evidence supports."],
    pricing: ["Pricing engine", "Price evidence, sale scenarios, and collection simulations."],
    selling: ["Listing preparation", "Your listing text and card photos, ready to review."],
    collection: ["Your collection", "Every card, with its evidence."],
    photos: ["Photo inbox", "Keep the originals. Review what matters."],
    purchases: ["Purchases", "Connect each card to its purchase evidence."],
  };
  return (
    <div className="app">
      <aside className="sidebar">
        <a href="/" className="brand">
          <CardMark size={36} />
          <span>SportsCards</span>
        </a>
        <nav aria-label="Main navigation" className="pe-main-nav">
          {[
            ["analysis", "Analysis", ChartNoAxesCombined],
            ["pricing", "Engine", SlidersHorizontal],
            ["selling", "Sell prep", ClipboardList],
            ["collection", "Collection", Smartphone],
            ["photos", "Photo inbox", Image],
            ["purchases", "Purchases", ShoppingCart],
          ].map(([key, title, Icon]) => (
            <button
              key={key}
              className={view === key ? "selected" : ""}
              onClick={() => setView(key)}
              aria-current={view === key ? "page" : undefined}
            >
              <Icon size={25} />
              {title}
            </button>
          ))}
        </nav>
        <div className="private">
          <span>Private collection</span>
          <small>Stored on your server.</small>
        </div>
      </aside>
      <main>
        <header>
          <div>
            <h1>{titles[view][0]}</h1>
            <p>{titles[view][1]}</p>
          </div>
          <button
            className="primary"
            disabled={!loaded}
            onClick={() => setUploading(true)}
          >
            <Upload size={23} />
            Upload photos
          </button>
        </header>
        {message && (
          <div className="error banner" role="alert">
            <span>{message}</span>
            <button
              className="icon-button"
              aria-label="Dismiss message"
              onClick={() => setMessage("")}
            >
              <X size={20} />
            </button>
          </div>
        )}
        {!loaded ? (
          <div className="empty">
            <h2>Connecting to your collection…</h2>
            <button
              onClick={() => refresh().catch((e) => setMessage(e.message))}
            >
              Retry connection
            </button>
          </div>
        ) : (
          <>
            {view !== "analysis" && view !== "pricing" && view !== "selling" && <div className="stats">
              {[
                [state.cards.length, "Cards"],
                [state.photos.length, "Photos"],
                [needReview, "Photos to review"],
              ].map(([n, label]) => (
                <div key={label}>
                  <strong>{n}</strong>
                  <span>{label}</span>
                </div>
              ))}
            </div>}
            {view === "analysis" ? <Analysis state={state} refresh={refresh} onCard={c => setSelected(c.id)} /> : view === "pricing" ? <PricingEngine state={state} refresh={refresh} onCard={c => setSelected(c.id)} /> : view === "selling" ? <SellingPrep onCard={c => setSelected(c.id)} /> : view === "collection" ? (
              <Collection
                state={state}
                onUpload={() => setUploading(true)}
                onCard={(c) => setSelected(c.id)}
              />
            ) : view === "photos" ? (
              <PhotoInbox
                state={state}
                refresh={refresh}
                notify={setMessage}
                onUpload={() => setUploading(true)}
              />
            ) : (
              <Purchases state={state} refresh={refresh} />
            )}
          </>
        )}
        {uploading && (
          <UploadDialog
            refresh={refresh}
            onClose={() => {
              setUploading(false);
              if (state.photos.length) setView("photos");
            }}
          />
        )}
        {card && (
          <CardDetail
            initialTab={view === "analysis" || view === "pricing" ? "valuation" : "details"}
            card={card}
            state={state}
            refresh={refresh}
            onClose={() => setSelected(null)}
          />
        )}
      </main>
    </div>
  );
}
