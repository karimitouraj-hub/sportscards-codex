import React from "react";
import { Search, Download } from "lucide-react";
import { CardMark } from "./ui";

export default function Collection({ state, onUpload, onCard }) {
  const [query, setQuery] = React.useState(""),
    [filter, setFilter] = React.useState("all"),
    [exportOpen, setExportOpen] = React.useState(false);
  const cards = state.cards
    .filter((c) =>
      [c.player, c.year, c.set, c.number, c.variant, c.visual_description, c.serial_number]
        .join(" ")
        .toLowerCase()
        .includes(query.toLowerCase()),
    )
    .filter(
      (c) =>
        filter === "all" ||
        (filter === "complete"
          ? [c.year, c.set, c.number, c.variant, c.grade, c.condition].every(
              Boolean,
            )
          : ![c.year, c.set, c.number, c.variant, c.grade, c.condition].every(
              Boolean,
            )),
    )
    .sort((a, b) => a.player.localeCompare(b.player));
  return (
    <>
      <div className="toolbar">
        <div className="search">
          <Search size={21} />
          <input
            aria-label="Search collection"
            placeholder="Search player, set, or card number"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <select
          aria-label="Filter cards"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">All cards</option>
          <option value="incomplete">Missing details</option>
          <option value="complete">Complete details</option>
        </select>
        <div className="export">
          <button
            onClick={() => setExportOpen(!exportOpen)}
            aria-expanded={exportOpen}
          >
            <Download size={20} />
            Export
          </button>
          {exportOpen && (
            <div className="export-menu">
              <a href="/api/export/json" download>
                Export JSON with evidence
              </a>
              <a href="/api/export/csv" download>
                Export collection CSV
              </a>
            </div>
          )}
        </div>
      </div>
      {state.cards.length > 0 && <p className="muted collection-count">
        {cards.length} of {state.cards.length} physical cards. Repeated photo views share one record.
      </p>}
      {!state.cards.length ? (
        <>
          <div className="empty">
            <CardMark size={88} />
            <h2>Start with your first photos</h2>
            <p>
              Upload up to 20 photos at a time. Review each card before you add it to
              your collection.
            </p>
            <button className="primary" onClick={onUpload}>
              Choose photos
            </button>
            <small>JPEG, PNG, WebP, HEIC and HEIF</small>
          </div>
          <div className="steps">
            {[
              ["Upload originals", "Add up to 20 clear photos at a time."],
              ["Review card details", "Check each card against its photo."],
              ["Keep the evidence", "Save to your private collection."],
            ].map(([title, description], i) => (
              <div key={title}>
                <span className="step-number">0{i + 1}</span>
                <div>
                  <strong>{title}</strong>
                  <small>{description}</small>
                </div>
              </div>
            ))}
          </div>
        </>
      ) : cards.length ? (
        <div className="collection-list">
          {cards.map((c) => {
            const obs = state.observations.find((o) => o.id === c.primary_observation_id) || state.observations.find((o) => o.card_id === c.id);
            return (
              <button
                className="collection-row"
                key={c.id}
                onClick={() => onCard(c)}
              >
                {obs ? (
                  <img
                    src={
                      "/media/crop/" + obs.id + "?v=" + (obs.crop_revision || 0)
                    }
                    alt={"Photo of " + c.player}
                  />
                ) : (
                  <CardMark />
                )}
                <div>
                  <h3>{c.player}</h3>
                  <p>
                    {[c.year, c.set, c.number && "#" + c.number]
                      .filter(Boolean)
                      .join(" · ") || "Card details incomplete"}
                  </p>
                  <small>
                    {[c.variant, c.grade, c.condition]
                      .filter(Boolean)
                      .join(" · ")}
                  </small>
                  {c.visual_description && <small>{c.visual_description}</small>}
                  {c.serial_number && <small>Serial {c.serial_number}</small>}
                </div>
                <span className="status">{c.evidence_state === "photo_reviewed" ? "Photo reviewed" : "User confirmed"}</span>
              </button>
            );
          })}
        </div>
      ) : (
        <div className="empty compact">
          <h2>No matching cards</h2>
          <p>Change the search or filter.</p>
        </div>
      )}
    </>
  );
}
