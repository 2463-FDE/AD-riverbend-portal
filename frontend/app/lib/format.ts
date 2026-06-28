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
