// Shared types mirroring the Riverbend gateway API contract.

export interface PortalUser {
  username: string;
  full_name: string;
  role: string;
}

export interface LoginResponse {
  token: string;
  user: PortalUser;
}

export interface PatientSummary {
  id: number;
  mrn: string;
  name: string;
  dob: string;
  gender: string;
  created_at: string;
}

export interface PatientListResponse {
  items: PatientSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface RecordItem {
  id: number;
  kind: string;
  body: string;
  // Lab-style records may carry structured result fields.
  test?: string;
  value?: string | number;
  unit?: string;
  reference_range?: string;
  status?: string; // normal | abnormal | high | low | ...
}

export interface EncounterBlock {
  encounter: {
    id: number;
    type: string;
    provider: string;
    summary: string;
    date?: string;
  };
  records: RecordItem[];
}

export interface RecordsResponse {
  patient_id: number;
  encounters: EncounterBlock[];
}

export interface Slot {
  id: number;
  provider: string;
  location: string;
  start_at: string;
  end_at: string;
  status: string;
}

export interface SlotsResponse {
  items: Slot[];
}

export interface Appointment {
  id: number;
  patient_id: number;
  provider: string;
  reason: string;
  location?: string;
  start_at?: string;
  end_at?: string;
  status: string;
}

// The projected coverage verdict the gateway closes at its boundary
// (services/gateway/app.py `_VisitChatVerdict`). Every field is optional there,
// so every field is optional here; `status` is the only one the portal renders
// a tone from, and its vocabulary is active | inactive | unknown | pending.
export interface EligibilityVerdict {
  active?: boolean | null;
  status?: string | null;
  payer?: string | null;
  checked_at?: string | null;
  observed_at?: string | null;
}

// eligibility-assistant: the four clerk menu selections, mirrored from the one
// declaration in contracts/visit-chat-turn.json (eligibility-assistant-D-45) and
// pinned equal to it by app/assistant/turn.contract.test.ts. These arrays are
// what the portal's closed <select>s render — the clerk cannot type a value.
export const QUESTION_TYPES = [
  "covered_today",
  "will_it_pay",
  "in_network",
  "referral_needed",
  "prior_auth",
  "who_pays_first",
  "copay",
  "portal_down",
  "emergency",
] as const;
export const PAYERS = [
  "unitedhealthcare",
  "aetna",
  "cigna",
  "humana",
  "anthem_blue",
  "medicare",
  "medicaid",
] as const;
export const PRODUCTS = [
  "commercial",
  "medicare_advantage",
  "medicaid_mco",
  "chip",
  "original_medicare",
  "unconfirmed",
] as const;
export const STATES = ["CA", "other_us", "unconfirmed"] as const;

export type QuestionType = (typeof QUESTION_TYPES)[number];
export type Payer = (typeof PAYERS)[number];
export type Product = (typeof PRODUCTS)[number];
export type UsState = (typeof STATES)[number];

// The turn's mode — WHICH PATH produced the reply (eligibility-assistant-D-33).
// A different field from `assistant` below: `assistant` is the health tri-state
// W3-SPEC-22 landed ("did an LLM fault escape"), `mode` names the path. Two
// fields, two meanings, both rendered.
export const TURN_MODES = [
  "real",
  "fixture",
  "fallback",
  "care_first",
  "refuse",
  "no_lookup",
] as const;
export type TurnMode = (typeof TURN_MODES)[number];

export const TURN_REASONS = [
  "emergency",
  "cross_patient",
  "validation_reject",
  "no_retrieval",
  "spend_stop",
  "model_failure",
] as const;
export type TurnReason = (typeof TURN_REASONS)[number];

export const TURN_OUTCOMES = [
  "active",
  "inactive",
  "unknown",
  "unavailable",
  "reverify",
  "conflict",
  "refuse_definitive",
  "refuse",
  "stop",
  "care_first",
] as const;
export type TurnOutcome = (typeof TURN_OUTCOMES)[number];

// One rendered citation: the four fields the assistant renders from the index
// row (title, id, section, version) — never document text.
export interface Citation {
  title: string;
  document_id: string;
  section: string;
  version: string;
}

// One turn of POST /ai/visit-chat. `visit_memory` and `assistant` are honest
// tri-states, not errors: "degraded"/"stale" ride on a successful turn. The
// five eligibility-assistant report fields are answer-only and the gateway
// degrades them (`citations` to [], the rest to null) rather than failing a
// turn over them, so every one is nullable here.
export interface VisitChatResponse {
  visit_id: string | null;
  visit_memory: "ok" | "stale" | "unavailable";
  reply: string;
  disclaimer: string;
  eligibility: EligibilityVerdict | null;
  assistant: "ok" | "degraded" | "unknown";
  citations: Citation[];
  mode: TurnMode | null;
  reason: TurnReason | null;
  outcome: TurnOutcome | null;
  model: string | null;
  correlation_id: string;
}

// One candidate-duplicate pair awaiting a human judgment
// (services/intake-service/schemas.py ReviewQueueItem). Deliberately narrower
// than a patients row: no SSN and no address — enough to judge a pair, no more.
export interface ReviewQueuePatient {
  id: number;
  name: string;
  dob?: string | null;
  created_via?: string | null;
  created_at?: string | null;
}

export interface ReviewQueueItem {
  id: number;
  patient_a: ReviewQueuePatient;
  patient_b: ReviewQueuePatient;
  source: string; // intake | retroactive
  created_at?: string | null;
}

export interface ReviewQueueResponse {
  items: ReviewQueueItem[];
}

export type Disposition = "duplicate_confirmed" | "not_duplicate";

// The relevant-records panel shown on chart open
// (services/records-service/schemas.py RelevantRecords). `duplicate_disclosure`
// is a bare enum by design — the disclosure says sibling charts MAY exist and
// never names one, so the surface cannot become a cross-chart navigation path.
export interface RelevantRecordItem {
  record_id: number;
  kind?: string | null;
  title?: string | null;
  occurred_at?: string | null;
  reason: "allergy" | "medication" | "recent";
}

export interface RelevantRecordsResponse {
  patient_id: number;
  duplicate_disclosure: "candidate" | "none";
  items: RelevantRecordItem[];
}

// One hit from the bounded free-text records search
// (services/records-service/schemas.py RecordSearchHit / RecordSearch). The
// response is bounded: `truncated` is the withheld-results signal, so the portal
// can tell a capped result set apart from an exhausted one (e6-SPEC-5/6). Shape
// declared in contracts/records-search.json, asserted consumer-side by
// frontend/app/records/search.contract.test.ts.
export interface RecordSearchHit {
  id: number;
  patient_id: number;
  kind?: string | null;
  title?: string | null;
  body?: string | null;
}

export interface RecordSearchResponse {
  hits: RecordSearchHit[];
  truncated: boolean;
}

export interface RoiRequest {
  id: number;
  patient_id: number;
  recipient: string;
  recipient_type: string;
  purpose: string;
  date_range_start: string;
  date_range_end: string;
  status: string;
  created_at?: string;
}
