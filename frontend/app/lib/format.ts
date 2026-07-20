// Small presentation helpers (dates, names). Defensive against missing/odd
// values coming back from the gateway.

export function fmtDateTime(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function fmtDate(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function fmtTimeRange(start?: string, end?: string): string {
  if (!start) return "—";
  const s = new Date(start);
  if (Number.isNaN(s.getTime())) return start;
  const opts: Intl.DateTimeFormatOptions = { hour: "numeric", minute: "2-digit" };
  const left = s.toLocaleTimeString(undefined, opts);
  if (!end) return left;
  const e = new Date(end);
  if (Number.isNaN(e.getTime())) return left;
  return `${left} – ${e.toLocaleTimeString(undefined, opts)}`;
}

export function firstName(full: string): string {
  return full.trim().split(/\s+/)[0] || full;
}

// --- Input entry formatters (F2 — UX audit 2026-07) -----------------------
// Display/entry convenience only. Callers store the formatted string in state;
// the wire payload is normalized to bare digits via `digitsOnly` before submit.
// These never touch PHI storage or the redaction path — they only shape what
// the patient sees while typing.

// SSN: digits only, auto-insert dashes as ###-##-#### (max 9 digits).
export function formatSsn(raw: string): string {
  const d = raw.replace(/\D/g, "").slice(0, 9);
  if (d.length <= 3) return d;
  if (d.length <= 5) return `${d.slice(0, 3)}-${d.slice(3)}`;
  return `${d.slice(0, 3)}-${d.slice(3, 5)}-${d.slice(5)}`;
}

// Phone: readability only — dash the first 10 digits as ###-###-####, keep any
// extra digits (e.g. an extension) appended undashed. Permissive by design.
export function formatPhone(raw: string): string {
  const digits = raw.replace(/\D/g, "");
  const head = digits.slice(0, 10);
  const tail = digits.slice(10);
  let out = head;
  if (head.length > 6) out = `${head.slice(0, 3)}-${head.slice(3, 6)}-${head.slice(6)}`;
  else if (head.length > 3) out = `${head.slice(0, 3)}-${head.slice(3)}`;
  return tail ? `${out}${tail}` : out;
}

// Strip a formatted value back to bare digits for the wire payload.
export function digitsOnly(v: string): string {
  return v.replace(/\D/g, "");
}
