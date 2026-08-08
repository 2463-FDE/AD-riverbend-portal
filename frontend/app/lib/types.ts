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

// One turn of POST /ai/visit-chat. `visit_memory` and `assistant` are honest
// tri-states, not errors: "degraded"/"stale" ride on a successful turn.
export interface VisitChatResponse {
  visit_id: string | null;
  visit_memory: "ok" | "stale" | "unavailable";
  reply: string;
  disclaimer: string;
  eligibility: EligibilityVerdict | null;
  assistant: "ok" | "degraded" | "unknown";
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
