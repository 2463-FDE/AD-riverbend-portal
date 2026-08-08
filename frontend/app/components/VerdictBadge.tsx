import type { EligibilityVerdict } from "../lib/types";

type Variant = "ok" | "warn" | "bad";

interface Tone {
  variant: Variant;
  label: string;
}

// Deliberately NOT StatusBadge's shared map, and deliberately not an extension
// of it (W3-SPEC-18). That map renders `unknown`/`unverified`/`inactive` as
// `neutral` while `denied` is `bad` — i.e. an unverified outcome reads quieter
// than a denial, the exact inversion this surface forbids. Widening the shared
// map would restyle the four pages already using it; a separate map is the
// smaller blast radius.
//
// The vocabulary is the eligibility path's own (active | inactive | unknown |
// pending — services/ai-assistant/eligibility_client.py:102). Anything outside
// it renders nothing: a tone this component had to guess at is a coverage
// verdict invented client-side, which is what W3-SPEC-6 rules out.
const TONES: Record<string, Tone> = {
  active: { variant: "ok", label: "Coverage active" },
  inactive: { variant: "bad", label: "No active coverage (payer-confirmed)" },
  unknown: { variant: "warn", label: "Unverified — not a denial" },
  pending: { variant: "warn", label: "Pending verification — not a denial" },
};

export function verdictTone(status: string | null | undefined): Tone | null {
  if (!status) return null;
  return TONES[status.toLowerCase().trim()] ?? null;
}

// A tone signal, not a second source of truth: the authoritative prose (with
// its payer and checked_at stamp) is the server-rendered `reply`.
export default function VerdictBadge({
  eligibility,
}: {
  eligibility: EligibilityVerdict | null | undefined;
}) {
  const tone = verdictTone(eligibility?.status);
  if (!tone) return null;
  return (
    <span
      className={`rb-badge rb-badge--${tone.variant}`}
      role="status"
      aria-label={`Eligibility: ${tone.label}`}
    >
      {tone.label}
    </span>
  );
}
