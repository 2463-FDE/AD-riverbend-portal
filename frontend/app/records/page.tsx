"use client";

import { useState } from "react";
import Card from "../components/Card";
import StatusBadge, { statusVariant } from "../components/StatusBadge";
import { IconRecords, IconLab, IconSearch, IconStethoscope, IconHeart } from "../components/icons";
import { apiFetch } from "../lib/session";
import type {
  EncounterBlock,
  RecordItem,
  RelevantRecordItem,
  RelevantRecordsResponse,
} from "../lib/types";
import { fmtDate } from "../lib/format";

// Fixed, client-authored, non-PHI. Shown when the helper cannot be reached OR
// answers something that is not its contract. It deliberately says BOTH things:
// the panel is missing, AND duplicate status is unconfirmed — an unanswered
// disclosure check must not read as "no duplicates", which is the fail-open
// version of the exact defect this surface exists to disclose.
const HELPER_UNAVAILABLE =
  "Relevant records could not be loaded, and duplicate-chart status is not confirmed. " +
  "Treat this record set as possibly incomplete and read the full history below.";

// The disclosure itself. No sibling chart ids, no links: it says other charts
// MAY exist, never which, so this cannot become a cross-chart navigation path
// (ADR 0005 rejects reading across charts no human has merged).
const DUPLICATE_DISCLOSURE =
  "This patient may have more than one chart. Records shown here are from this chart only, " +
  "so the set may be incomplete — check with Health Information Management before relying " +
  "on it as a complete history. Merging charts is an HIM procedure.";

const REASON_LABEL: Record<RelevantRecordItem["reason"], string> = {
  allergy: "Allergy recorded",
  medication: "Medication recorded",
  recent: "Recent",
};

function isRelevantRecords(d: unknown): d is RelevantRecordsResponse {
  if (!d || typeof d !== "object") return false;
  const v = d as RelevantRecordsResponse;
  if (typeof v.patient_id !== "number") return false;
  if (v.duplicate_disclosure !== "candidate" && v.duplicate_disclosure !== "none") return false;
  if (!Array.isArray(v.items)) return false;
  return v.items.every(
    (i) =>
      i &&
      typeof i === "object" &&
      typeof i.record_id === "number" &&
      (i.reason === "allergy" || i.reason === "medication" || i.reason === "recent")
  );
}

function isResult(r: RecordItem): boolean {
  return Boolean(r.test || r.value !== undefined || r.reference_range);
}

export default function RecordsPage() {
  // The records view loads by a patient id taken straight off the input/URL.
  // The id is a sequential integer and the backend does NOT check ownership
  // (IDOR — intentional teaching point; see docs/handover/portal.har). We pass
  // whatever id is entered straight through to /api/records.
  const [patientId, setPatientId] = useState("1042");
  const [data, setData] = useState<EncounterBlock[] | null>(null);
  const [selected, setSelected] = useState<EncounterBlock | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [relevant, setRelevant] = useState<RelevantRecordsResponse | null>(null);
  const [relevantFailed, setRelevantFailed] = useState(false);

  async function load() {
    setBusy(true);
    setStatus("");
    setSelected(null);
    setRelevant(null);
    setRelevantFailed(false);
    try {
      const res = await apiFetch(`/api/records?patient_id=${encodeURIComponent(patientId)}`);
      const json = await res.json();
      const encounters: EncounterBlock[] = json.encounters ?? [];
      setData(encounters);
      setSelected(encounters[0] ?? null);
      if (encounters.length === 0) setStatus("No records found for this patient.");
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Could not load records.");
      setData([]);
    } finally {
      setBusy(false);
    }
    // Fetched SEPARATELY and awaited after the chart, so retrieval is an aid and
    // never a gate on chart access (W2-SPEC-2): if this call fails, everything
    // above has already been set and the chart renders regardless.
    void loadRelevant();
  }

  async function loadRelevant() {
    try {
      const res = await apiFetch(
        `/api/patients/${encodeURIComponent(patientId)}/relevant-records`
      );
      if (!res.ok) {
        setRelevantFailed(true);
        return;
      }
      const json: unknown = await res.json();
      if (!isRelevantRecords(json)) {
        setRelevantFailed(true);
        return;
      }
      setRelevant(json);
    } catch {
      setRelevantFailed(true);
    }
  }

  return (
    <div className="rb-stack">
      <div className="rb-page-head">
        <h1>Health Records</h1>
        <p>Look up a patient&apos;s encounters and lab results.</p>
      </div>

      <Card>
        <div className="rb-field" style={{ maxWidth: 360, marginBottom: 0 }}>
          <label className="rb-field__label" htmlFor="rec-patient">
            Patient ID
          </label>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              id="rec-patient"
              className="rb-input"
              value={patientId}
              onChange={(e) => setPatientId(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && load()}
              inputMode="numeric"
            />
            <button className="rb-btn rb-btn--primary" onClick={load} disabled={busy} type="button">
              {busy ? "Loading…" : <><IconSearch width={16} height={16} /> Load</>}
            </button>
          </div>
          <span className="rb-field__hint">Demo patient ID defaults to 1042.</span>
        </div>
      </Card>

      {status && (
        <div className="rb-alert rb-alert--info" role="status">
          {status}
        </div>
      )}

      {relevant?.duplicate_disclosure === "candidate" && (
        <div className="rb-alert rb-alert--warn" role="status">
          {DUPLICATE_DISCLOSURE}
        </div>
      )}

      {relevantFailed && (
        <div className="rb-alert rb-alert--warn" role="status">
          {HELPER_UNAVAILABLE}
        </div>
      )}

      {relevant && relevant.items.length > 0 && (
        <Card title="Most relevant records" icon={<IconHeart />}>
          <div className="rb-list">
            {relevant.items.map((item) => (
              <div key={item.record_id} className="rb-listrow">
                <div className="rb-listrow__main">
                  <div className="rb-listrow__title">{item.title || item.kind || "Record"}</div>
                  <div className="rb-listrow__meta">
                    <span className="rb-badge rb-badge--neutral">
                      {REASON_LABEL[item.reason]}
                    </span>
                    {item.kind && <span>{item.kind}</span>}
                    {item.occurred_at && <span>{fmtDate(item.occurred_at)}</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <p className="rb-field__hint" style={{ marginTop: 8 }}>
            Ranked by allergy and medication entries first, then recency. The full history is
            below — this panel narrows where to look, it does not replace it.
          </p>
        </Card>
      )}

      {data && data.length > 0 && (
        <div className="rb-grid rb-grid--2">
          {/* Encounter list */}
          <Card title="Encounters" icon={<IconRecords />}>
            <div className="rb-list">
              {data.map((block) => {
                const active = selected?.encounter.id === block.encounter.id;
                return (
                  <button
                    key={block.encounter.id}
                    type="button"
                    className="rb-listrow rb-listrow--clickable"
                    aria-pressed={active}
                    style={active ? { borderColor: "var(--rb-primary)" } : undefined}
                    onClick={() => setSelected(block)}
                  >
                    <div className="rb-listrow__main">
                      <div className="rb-listrow__title">{block.encounter.type}</div>
                      <div className="rb-listrow__meta">
                        <span><IconStethoscope width={15} height={15} /> {block.encounter.provider}</span>
                        {block.encounter.date && <span>{fmtDate(block.encounter.date)}</span>}
                        <span>{block.records.length} record{block.records.length === 1 ? "" : "s"}</span>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </Card>

          {/* Encounter detail */}
          <Card
            title={selected ? selected.encounter.type : "Encounter detail"}
            icon={<IconLab />}
          >
            {selected ? (
              <EncounterDetail block={selected} />
            ) : (
              <div className="rb-empty">Select an encounter to view details.</div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

function EncounterDetail({ block }: { block: EncounterBlock }) {
  const results = block.records.filter(isResult);
  const notes = block.records.filter((r) => !isResult(r));

  return (
    <div>
      <div className="rb-listrow__meta" style={{ marginBottom: 6 }}>
        <span><IconStethoscope width={15} height={15} /> {block.encounter.provider}</span>
        {block.encounter.date && <span>{fmtDate(block.encounter.date)}</span>}
      </div>
      {block.encounter.summary && (
        <p className="rb-muted">{block.encounter.summary}</p>
      )}

      {results.length > 0 && (
        <>
          <h3 style={{ marginTop: 18 }}>Lab results</h3>
          <table className="rb-table">
            <thead>
              <tr>
                <th>Test</th>
                <th>Value</th>
                <th>Reference range</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => {
                const abnormal = statusVariant(r.status) === "bad";
                return (
                  <tr key={r.id}>
                    <td>{r.test || r.kind}</td>
                    <td className={`rb-table__num${abnormal ? " rb-table__num--abnormal" : ""}`}>
                      {r.value ?? "—"}
                      {r.unit ? ` ${r.unit}` : ""}
                    </td>
                    <td className="rb-ref">{r.reference_range ?? "—"}</td>
                    <td><StatusBadge status={r.status || "normal"} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </>
      )}

      {notes.length > 0 && (
        <>
          <h3 style={{ marginTop: 18 }}>Records &amp; notes</h3>
          <div className="rb-list">
            {notes.map((r) => (
              <div key={r.id} className="rb-listrow" style={{ display: "block" }}>
                <span className="rb-badge rb-badge--neutral" style={{ marginBottom: 6 }}>
                  {r.kind}
                </span>
                <div>{r.body}</div>
              </div>
            ))}
          </div>
        </>
      )}

      {results.length === 0 && notes.length === 0 && (
        <div className="rb-empty">No records in this encounter.</div>
      )}
    </div>
  );
}
