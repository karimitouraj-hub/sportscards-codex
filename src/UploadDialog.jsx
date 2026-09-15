import React from "react";
import { Upload, CheckCircle2, AlertCircle } from "lucide-react";
import { upload } from "./api";
import { Modal } from "./ui";

const MAX_PHOTOS_PER_BATCH = 20;

export default function UploadDialog({ onClose, refresh }) {
  const [items, setItems] = React.useState([]),
    [busy, setBusy] = React.useState(false),
    [error, setError] = React.useState("");
  const update = (id, patch) =>
    setItems((old) => old.map((i) => (i.id === id ? { ...i, ...patch } : i)));
  async function run(list) {
    setBusy(true);
    setError("");
    for (const item of list) {
      update(item.id, { state: "Uploading", progress: 0, error: "" });
      try {
        const result = await upload(item.file, (p) =>
          update(item.id, {
            progress: p,
            state: p === 100 ? "Checking photo" : "Uploading",
          }),
        );
        update(item.id, {
          state: result.status === "duplicate" ? "Duplicate" : "Saved",
          progress: 100,
        });
        await refresh();
      } catch (e) {
        update(item.id, { state: "Failed", error: e.message });
      }
    }
    setBusy(false);
  }
  function select(files) {
    if (files.length > MAX_PHOTOS_PER_BATCH) {
      setError(`Select up to ${MAX_PHOTOS_PER_BATCH} photos at a time.`);
      return;
    }
    if (!files.length) return;
    const list = Array.from(files).map((file, i) => ({
      id: Date.now() + i,
      file,
      state: "Waiting",
      progress: 0,
    }));
    setItems(list);
    run(list);
  }
  return (
    <Modal title="Upload photos" onClose={() => !busy && onClose()}>
      <p>
        Select up to {MAX_PHOTOS_PER_BATCH} photos at a time. Original photos stay
        on your server. Existing photos do not count toward this upload limit.
      </p>
      <label
        className="dropzone"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          if (!busy) select(e.dataTransfer.files);
        }}
      >
        <Upload size={32} />
        <strong>Select photos or drop them here</strong>
        <span>JPEG, PNG, WebP, HEIC and HEIF · 40 MB per photo</span>
        <input
          aria-label="Choose photos to upload"
          type="file"
          accept="image/jpeg,image/png,image/webp,.heic,.heif"
          multiple
          disabled={busy}
          onChange={(e) => select(e.target.files)}
        />
      </label>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div aria-live="polite">
        {items.map((i) => (
          <div className="upload-row" key={i.id}>
            <div className="row">
              <strong>{i.file.name}</strong>
              <span>
                {i.state === "Saved" || i.state === "Duplicate" ? (
                  <CheckCircle2 size={18} />
                ) : i.state === "Failed" ? (
                  <AlertCircle size={18} />
                ) : null}{" "}
                {i.state}
              </span>
            </div>
            <progress max="100" value={i.progress} />
            {i.error && <p className="error">{i.error}</p>}
            {i.state === "Failed" && !busy && (
              <button onClick={() => run([i])}>Retry photo</button>
            )}
          </div>
        ))}
      </div>
      <div className="actions">
        <button disabled={busy} className="primary" onClick={onClose}>
          {busy ? "Upload in progress" : "Done"}
        </button>
      </div>
    </Modal>
  );
}
