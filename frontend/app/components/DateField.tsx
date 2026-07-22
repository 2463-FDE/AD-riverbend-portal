"use client";

import { useEffect, useRef, useState } from "react";
import { DayPicker } from "react-day-picker";
import "react-day-picker/style.css";

// ISO (YYYY-MM-DD) <-> Date using LOCAL calendar fields only.
//
// Never `new Date("2020-01-15")`: that parses as UTC midnight and, in any
// negative-offset timezone, renders as the previous calendar day — silently
// shifting a date of birth by one day. Both directions below stay in local
// time so a date round-trips to the exact string it came from. (ADR 0008.)
function isoToDate(iso: string): Date | undefined {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return undefined;
  const date = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return Number.isNaN(date.getTime()) ? undefined : date;
}

function dateToIso(date: Date): string {
  const y = date.getFullYear();
  const mo = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${mo}-${d}`;
}

// A date-entry control that opens a styled calendar popover but holds and emits
// a `YYYY-MM-DD` string — byte-for-byte what `<input type="date">` produced, so
// the intake / ROI payloads to the gateway are unchanged. `DateField` is the
// only consumer of react-day-picker (ADR 0008); pages use it like `Field`.
export default function DateField({
  id,
  label,
  value,
  onChange,
  required = false,
  hint,
  disableFuture = false,
  fromYear = 1900,
}: {
  id: string;
  label: string;
  value: string; // ISO YYYY-MM-DD, or "" when empty
  onChange: (iso: string) => void;
  required?: boolean;
  hint?: string;
  // Records dates and dates of birth cannot be in the future.
  disableFuture?: boolean;
  // Earliest selectable year (bounds the year dropdown). Defaults to 1900.
  // This default is load-bearing: with `captionLayout="dropdown"` and no
  // `startMonth`, react-day-picker v9 collapses the year dropdown to a rolling
  // ~100-year window (today−100y .. today), a *hidden* lower wall that is worse
  // than a native `<input type="date">` (which accepts any typed year). Pinning
  // an explicit floor means no consumer silently inherits that wall; 1900
  // covers any living patient's DOB and any real records date. Callers reaching
  // further back pass a smaller `fromYear`.
  fromYear?: number;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const selected = isoToDate(value);

  // Close on outside click / Escape — mirrors the user-menu pattern in AppShell.
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const today = new Date();
  const startMonth = fromYear ? new Date(fromYear, 0) : undefined;
  const endMonth = disableFuture ? today : undefined;

  // Display the selected date from the already-parsed local Date (not via
  // fmtDate(iso), which would UTC-parse and can drift a day).
  const display = selected
    ? selected.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
    : "Select a date";

  return (
    <div className="rb-field">
      <label className="rb-field__label" htmlFor={id}>
        {label}
        {required && <span className="rb-field__req" aria-hidden="true">*</span>}
      </label>
      <div className="rb-datefield" ref={wrapRef}>
        <button
          id={id}
          type="button"
          className="rb-input rb-datefield__trigger"
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-required={required}
          onClick={() => setOpen((o) => !o)}
        >
          <span className={value ? undefined : "rb-datefield__placeholder"}>{display}</span>
        </button>
        {open && (
          <div className="rb-datefield__pop" role="dialog" aria-label={label}>
            <DayPicker
              mode="single"
              selected={selected}
              defaultMonth={selected}
              startMonth={startMonth}
              endMonth={endMonth}
              captionLayout="dropdown"
              disabled={disableFuture ? { after: today } : undefined}
              autoFocus
              onSelect={(d) => {
                onChange(d ? dateToIso(d) : "");
                if (d) setOpen(false);
              }}
            />
          </div>
        )}
      </div>
      {hint && <span className="rb-field__hint">{hint}</span>}
    </div>
  );
}
