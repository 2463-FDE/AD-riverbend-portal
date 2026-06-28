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
