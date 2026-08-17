import type { RecordSearchResponse } from "../lib/types";

// Consumer half of contracts/records-search.json (e6-D-16): the fields the
// portal reads and the guard it reads them through, asserted equal to the
// declaration by frontend/app/records/search.contract.test.ts. Kept in a plain
// module rather than in page.tsx because Next's App Router forbids a route file
// from exporting anything but its page conventions.
export const RECORD_SEARCH_FIELDS = ["hits", "truncated"] as const;
export const RECORD_SEARCH_HIT_FIELDS = ["id", "patient_id", "kind", "title", "body"] as const;

export function isRecordSearch(d: unknown): d is RecordSearchResponse {
  if (!d || typeof d !== "object") return false;
  const v = d as RecordSearchResponse;
  if (typeof v.truncated !== "boolean") return false;
  if (!Array.isArray(v.hits)) return false;
  return v.hits.every(
    (h) => h && typeof h === "object" && typeof h.id === "number" && typeof h.patient_id === "number"
  );
}
