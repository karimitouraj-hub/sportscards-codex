import React from "react";
import { api } from "./api";
import { Field, IdentityFields, Modal, Notice } from "./ui";

export default function PhotoInbox({ state, refresh, notify, onUpload }) {
  const [selected, setSelected] = React.useState(null),
    [review, setReview] = React.useState(null),
    [adding, setAdding] = React.useState(false);
  const photo = state.photos.find((p) => p.id === selected);
  async function act(path, body = {}, method = "POST") {
    try {
      await api(path, method, body);
      await refresh();
    } catch (e) {
      notify(e.message);
    }
  }
  if (!state.photos.length)
    return (
      <div className="empty">
        <h2>Your photo inbox is empty</h2>
        <p>Upload the first batch to start card review.</p>
        <button className="primary" onClick={onUpload}>
          Choose photos
        </button>
      </div>
    );
  return (
    <>
      <Notice>
        Rectangle detection suggests crops. Check for missed cards, extra
        rectangles, and overlapping cards before you finish a photo.
      </Notice>
      {photo ? (
        <>
          <button className="back" onClick={() => setSelected(null)}>
            Back to photo inbox
          </button>
          <div className="photo-review">
            <div>
              <div className="photo-canvas">
                <img
                  src={"/media/preview/" + photo.id}
                  alt="Original photo preview"
                />
                {state.observations
                  .filter(
                    (o) => o.photo_id === photo.id && o.status !== "ignored",
                  )
                  .map((o, i) => (
                    <button
                      key={o.id}
                      className={
                        "crop-box " +
                        (o.status === "confirmed" ? "confirmed" : "")
                      }
                      aria-label={"Review observation " + (i + 1)}
                      style={{
                        left: o.bbox[0] * 100 + "%",
                        top: o.bbox[1] * 100 + "%",
                        width: o.bbox[2] * 100 + "%",
                        height: o.bbox[3] * 100 + "%",
                      }}
                      onClick={() => setReview(o)}
                    >
                      <span>{i + 1}</span>
                    </button>
                  ))}
              </div>
              <a className="text-link" href={"/media/original/" + photo.id}>
                Download original
              </a>
            </div>
            <div>
              <h2>Review this photo</h2>
              <p className="muted">{decodeName(photo.filename)}</p>
              <div className="actions left">
                <button onClick={() => setAdding(true)}>Add missed card</button>
                <button
                  className="primary"
                  onClick={() => act("/photos/" + photo.id + "/review")}
                >
                  {photo.review_complete
                    ? "Photo reviewed"
                    : "Finish photo review"}
                </button>
              </div>
              {state.observations
                .filter((o) => o.photo_id === photo.id)
                .map((o, i) => (
                  <button
                    className="observation-row"
                    key={o.id}
                    onClick={() => setReview(o)}
                  >
                    <img
                      src={
                        "/media/crop/" + o.id + "?v=" + (o.crop_revision || 0)
                      }
                      alt={"Card observation " + (i + 1)}
                    />
                    <span>
                      <strong>{state.cards.find((c) => c.id === o.card_id)?.player || "Observation " + (i + 1)}</strong>
                      <small>
                        {o.status.replaceAll("_", " ")} · {o.side}
                      </small>
                      {o.review_note && <small>{o.review_note}</small>}
                    </span>
                  </button>
                ))}
            </div>
          </div>
        </>
      ) : (
        <div className="photo-list">
          {state.photos.map((p, i) => {
            const job = state.jobs.find((j) => j.photo_id === p.id);
            return (
              <div className="photo-row" key={p.id}>
                <img src={"/media/preview/" + p.id} alt="Uploaded photo" />
                <div>
                  <h3>Photo {i + 1} · {decodeName(p.filename)}</h3>
                  <p>
                    {p.width} × {p.height} ·{" "}
                    {(p.bytes / 1024 / 1024).toFixed(1)} MB
                  </p>
                  <small>
                    {p.review_complete
                      ? "Reviewed"
                      : job?.state === "done"
                        ? "Needs review"
                        : job?.state}
                  </small>
                  <small className="photo-count">{state.observations.filter((o) => o.photo_id === p.id && o.status !== "ignored").length} card views</small>
                  {job?.error && <p className="error">{job.error}</p>}
                </div>
                {job?.state === "done" ? (
                  <button onClick={() => setSelected(p.id)}>
                    Review photo
                  </button>
                ) : job?.state === "failed" ? (
                  <button onClick={() => act("/photos/" + p.id + "/retry")}>
                    Retry processing
                  </button>
                ) : (
                  <span className="muted">Processing…</span>
                )}
              </div>
            );
          })}
        </div>
      )}
      {review && (
        <ObservationDialog
          observation={state.observations.find((o) => o.id === review.id)}
          photo={state.photos.find((p) => p.id === review.photo_id)}
          state={state}
          refresh={refresh}
          onClose={() => setReview(null)}
        />
      )}
      {adding && (
        <CropDialog
          photo={photo}
          onClose={() => setAdding(false)}
          refresh={refresh}
        />
      )}
    </>
  );
}
function decodeName(name) {
  try {
    return decodeURIComponent(name);
  } catch {
    return name;
  }
}
function CropFields({ box, setBox }) {
  return (
    <div className="form-grid">
      {["Left (%)", "Top (%)", "Width (%)", "Height (%)"].map((label, i) => (
        <Field
          key={label}
          label={label}
          type="number"
          step="0.1"
          min="0"
          max="100"
          value={Math.round(box[i] * 1000) / 10}
          onChange={(e) =>
            setBox(
              box.map((v, n) => (n === i ? Number(e.target.value) / 100 : v)),
            )
          }
        />
      ))}
    </div>
  );
}
function CropDialog({ photo, onClose, refresh }) {
  const [box, setBox] = React.useState([0, 0, 1, 1]),
    [error, setError] = React.useState(""),
    [busy, setBusy] = React.useState(false);
  async function save(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/observations", "POST", { photo_id: photo.id, bbox: box });
      await refresh();
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Add missed card" onClose={onClose}>
      <CropPreview photo={photo} box={box} />
      <p>
        Set the rectangle around one card. Coordinates use the displayed photo
        orientation.
      </p>
      <form onSubmit={save}>
        <CropFields box={box} setBox={setBox} />
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="actions">
          <button className="primary" disabled={busy}>
            Add observation
          </button>
        </div>
      </form>
    </Modal>
  );
}
function CropPreview({ photo, box }) {
  return (
    <div className="photo-canvas crop-preview">
      <img src={"/media/preview/" + photo.id} alt="Crop position in photo" />
      <div
        className="crop-box"
        style={{
          left: box[0] * 100 + "%",
          top: box[1] * 100 + "%",
          width: box[2] * 100 + "%",
          height: box[3] * 100 + "%",
        }}
      />
    </div>
  );
}
function ObservationDialog({ observation: o, photo, state, refresh, onClose }) {
  const [details, setDetails] = React.useState({}),
    [side, setSide] = React.useState(o.side),
    [box, setBox] = React.useState(o.bbox),
    [rotation, setRotation] = React.useState(o.rotation || 0),
    [link, setLink] = React.useState(""),
    [error, setError] = React.useState(""),
    [busy, setBusy] = React.useState(false);
  async function action(fn, close = true) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
      if (close) onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Review card observation" wide onClose={onClose}>
      <div className="review-dialog">
        <div>
          <img className="reviewed-crop"
            src={"/media/crop/" + o.id + "?v=" + (o.crop_revision || 0)}
            alt="Saved card crop" />
          <details>
            <summary>Correct the crop</summary>
            <CropPreview photo={photo} box={box} />
            <CropFields box={box} setBox={setBox} />
            <Field label="Rotate crop">
              <select value={rotation} onChange={(e) => setRotation(Number(e.target.value))}>
                <option value={0}>Original orientation</option>
                <option value={90}>90° left</option>
                <option value={180}>180°</option>
                <option value={270}>90° right</option>
              </select>
            </Field>
            <button
              disabled={busy}
              onClick={() =>
                action(
                  () =>
                    api("/observations/" + o.id, "PATCH", { bbox: box, side, rotation }),
                  false,
                )
              }
            >
              Save crop
            </button>
          </details>
          <Field label="Card side">
            <select value={side} onChange={(e) => setSide(e.target.value)}>
              <option value="unknown">Unknown</option>
              <option value="front">Front</option>
              <option value="back">Back</option>
            </select>
          </Field>
          <button
            disabled={busy}
            onClick={() =>
              action(
                () => api("/observations/" + o.id + "/recognize", "POST", {}),
                false,
              )
            }
          >
            Read text from crop
          </button>
          {o.identity_proposal?.evidence_text && (
            <details>
              <summary>Extracted text · Unconfirmed</summary>
              <p className="muted">
                Check this text against the photo. It may contain errors.
              </p>
              <pre className="ocr-text">
                {o.identity_proposal.evidence_text}
              </pre>
            </details>
          )}
        </div>
        <div>
          {o.card_id ? (
            <>
              <h3>This observation is linked</h3>
              <p>{state.cards.find((c) => c.id === o.card_id)?.player}</p>
              <button
                disabled={busy}
                onClick={() =>
                  action(() =>
                    api("/observations/" + o.id, "PATCH", { bbox: box, side, rotation }),
                  )
                }
              >
                Save observation
              </button>
            </>
          ) : (
            <>
              <Notice>
                Identity is unresolved. Enter only details supported by the card
                or your purchase evidence.
              </Notice>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  action(async () => {
                    await api("/observations/" + o.id, "PATCH", {
                      bbox: box,
                      side,
                      rotation,
                    });
                    await api("/cards", "POST", {
                      ...details,
                      side,
                      observation_id: o.id,
                    });
                  });
                }}
              >
                <IdentityFields value={details} onChange={setDetails} />
                <div className="actions">
                  <button disabled={busy} className="primary">
                    Add as a new physical card
                  </button>
                </div>
              </form>
              {state.cards.length > 0 && (
                <div className="link-section">
                  <Field label="Or link to an existing physical card">
                    <select
                      value={link}
                      onChange={(e) => setLink(e.target.value)}
                    >
                      <option value="">Select a card</option>
                      {state.cards.map((c) => (
                        <option value={c.id} key={c.id}>
                          {c.player} · {c.year} {c.set} #{c.number} ·{" "}
                          {c.id.slice(0, 6)}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <button
                    disabled={!link || busy}
                    onClick={() =>
                      action(() =>
                        api("/cards/" + link + "/link", "POST", {
                          observation_id: o.id,
                          side,
                        }),
                      )
                    }
                  >
                    Link this side
                  </button>
                </div>
              )}
              <button
                className="text-link"
                disabled={busy}
                onClick={() =>
                  action(() =>
                    api("/observations/" + o.id, "PATCH", {
                      status:
                        o.status === "ignored" ? "needs_review" : "ignored",
                    }),
                  )
                }
              >
                {o.status === "ignored"
                  ? "Restore observation"
                  : "Ignore: this is not a card"}
              </button>
            </>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </div>
      </div>
    </Modal>
  );
}
