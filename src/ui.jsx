import React from "react";
import { X } from "lucide-react";
import { fields, labels } from "./api";

export function CardMark({ size = 44 }) {
  return (
    <svg
      width={size}
      height={size * 1.18}
      viewBox="0 0 60 72"
      fill="none"
      aria-hidden="true"
    >
      <rect
        x="7"
        y="15"
        width="36"
        height="51"
        rx="3"
        transform="rotate(-7 7 15)"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <rect
        x="14"
        y="8"
        width="36"
        height="53"
        rx="3"
        stroke="currentColor"
        strokeWidth="1.8"
      />
      <rect
        x="23"
        y="3"
        width="36"
        height="55"
        rx="3"
        transform="rotate(5 23 3)"
        fill="var(--surface)"
        stroke="currentColor"
        strokeWidth="1.8"
      />
    </svg>
  );
}
export function Field({ label, children, ...props }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children || <input {...props} />}
    </label>
  );
}
export function IdentityFields({ value, onChange }) {
  return (
    <div className="form-grid">
      {fields.map((k) => (
        <Field
          key={k}
          label={labels[k]}
          value={value[k] || ""}
          required={k === "player"}
          maxLength={250}
          onChange={(e) => onChange({ ...value, [k]: e.target.value })}
          placeholder={
            k === "grade"
              ? "Raw, or exact certified grade"
              : k === "variant"
                ? "Base, or exact parallel"
                : undefined
          }
        />
      ))}
    </div>
  );
}
export function Modal({ title, children, onClose, wide = false }) {
  const ref = React.useRef(null);
  const titleId = React.useId();
  React.useEffect(() => {
    const dialog = ref.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={wide ? "modal wide" : "modal"}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <div className="modal-head">
        <h2 id={titleId}>{title}</h2>
        <button
          className="icon-button"
          aria-label="Close dialog"
          onClick={onClose}
        >
          <X size={22} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Notice({ children }) {
  return <p className="notice">{children}</p>;
}
