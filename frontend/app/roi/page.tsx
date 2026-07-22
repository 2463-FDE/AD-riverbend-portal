"use client";

import { useCallback, useEffect, useState } from "react";
import Card from "../components/Card";
import DateField from "../components/DateField";
import StatusBadge from "../components/StatusBadge";
import { IconRoi, IconPlus } from "../components/icons";
import { apiFetch } from "../lib/session";
import type { RoiRequest } from "../lib/types";
import { fmtDate } from "../lib/format";

const DEFAULT_PATIENT_ID = "1042";

const RECIPIENT_TYPES = [
  "Healthcare provider",
  "Insurance company",
  "Attorney",
  "Employer",
  "Patient / personal",
  "Government agency",
  "Other",
];

const PURPOSES = [
  "Continuity of care",
  "Insurance claim",
  "Legal proceeding",
  "Personal records",
  "Disability / FMLA",
  "Second opinion",
  "Other",
];

export default function RoiPage() {
  const [patientId, setPatientId] = useState(DEFAULT_PATIENT_ID);
  const [recipient, setRecipient] = useState("");
  const [recipientType, setRecipientType] = useState(RECIPIENT_TYPES[0]);
  const [purpose, setPurpose] = useState(PURPOSES[0]);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const [requests, setRequests] = useState<RoiRequest[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [busyFulfill, setBusyFulfill] = useState<number | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const load = useCallback(async () => {
    setRequests(null);
    try {
      const r = await apiFetch(`/api/roi/requests?patient_id=${encodeURIComponent(patientId)}`);
      const d = await r.json();
      setRequests(Array.isArray(d) ? d : (d.items ?? []));
    } catch {
      setRequests([]);
    }
  }, [patientId]);

  useEffect(() => {
    load();
  }, [load]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const r = await apiFetch("/api/roi/requests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          patient_id: Number(patientId) || patientId,
          recipient,
          recipient_type: recipientType,
          purpose,
          date_range_start: start,
          date_range_end: end,
        }),
      });
      if (!r.ok) throw new Error();
      setMsg({ kind: "ok", text: "Records release request submitted." });
      setRecipient("");
      setStart("");
      setEnd("");
      await load();
    } catch {
      setMsg({ kind: "err", text: "Could not submit the request. Please try again." });
    } finally {
      setBusy(false);
    }
  }

  async function fulfill(req: RoiRequest) {
    setBusyFulfill(req.id);
    setMsg(null);
    try {
      const r = await apiFetch(`/api/roi/requests/${req.id}/fulfill`, { method: "POST" });
      if (!r.ok) throw new Error();
      setMsg({ kind: "ok", text: `Request #${req.id} marked fulfilled.` });
      await load();
    } catch {
      setMsg({ kind: "err", text: "Could not fulfill that request." });
    } finally {
      setBusyFulfill(null);
    }
  }

  return (
    <div className="rb-stack">
      <div className="rb-page-head">
        <h1>Release of Information</h1>
        <p>Request that your health records be released to a third party.</p>
      </div>

      {msg && (
        <div className={`rb-alert rb-alert--${msg.kind === "ok" ? "ok" : "err"}`} role="status">
          {msg.text}
        </div>
      )}

      <div className="rb-grid rb-grid--2">
        <Card title="New release request" icon={<IconPlus />}>
          <form onSubmit={submit}>
            <div className="rb-field">
              <label className="rb-field__label" htmlFor="roi-patient">
                Patient ID<span className="rb-field__req" aria-hidden="true">*</span>
              </label>
              <input id="roi-patient" className="rb-input" value={patientId}
                onChange={(e) => setPatientId(e.target.value)} required inputMode="numeric" />
            </div>

            <div className="rb-field">
              <label className="rb-field__label" htmlFor="roi-recipient">
                Recipient<span className="rb-field__req" aria-hidden="true">*</span>
              </label>
              <input id="roi-recipient" className="rb-input" value={recipient}
                onChange={(e) => setRecipient(e.target.value)} required
                placeholder="" />
              <span className="rb-field__hint">Name of the person or organization receiving the records.</span>
            </div>

            <div className="rb-field-row">
              <div className="rb-field">
                <label className="rb-field__label" htmlFor="roi-rtype">Recipient type</label>
                <select id="roi-rtype" className="rb-select" value={recipientType}
                  onChange={(e) => setRecipientType(e.target.value)}>
                  {RECIPIENT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div className="rb-field">
                <label className="rb-field__label" htmlFor="roi-purpose">Purpose</label>
                <select id="roi-purpose" className="rb-select" value={purpose}
                  onChange={(e) => setPurpose(e.target.value)}>
                  {PURPOSES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
            </div>

            {/* Records dates can predate any recent cutoff (migrated charts,
                lifetime history, legal/insurance discovery), so we rely on
                DateField's default 1900 floor rather than a recent one. We do
                NOT omit the floor: with captionLayout="dropdown" an unset
                startMonth silently collapses the year dropdown to today−100y,
                a hidden wall that would block pre-~1926 record dates. 1900
                reaches back past any living patient's earliest record. Only the
                future is barred (records cannot postdate today). Per ADR 0008. */}
            <div className="rb-field-row">
              <DateField id="roi-start" label="Records from" value={start}
                disableFuture onChange={setStart} />
              <DateField id="roi-end" label="Records to" value={end}
                disableFuture onChange={setEnd} />
            </div>

            <button className="rb-btn rb-btn--primary rb-btn--block" disabled={busy} type="submit">
              {busy ? (
                <><span className="rb-spinner" aria-hidden="true" /> Submitting…</>
              ) : (
                "Submit request"
              )}
            </button>
          </form>
        </Card>

        <Card title="Existing requests" icon={<IconRoi />}
          action={<button className="rb-btn rb-btn--ghost rb-btn--sm" onClick={load} type="button">Refresh</button>}>
          {requests === null ? (
            <div className="rb-loading">
              <span className="rb-spinner rb-spinner--dark" aria-hidden="true" /> Loading requests…
            </div>
          ) : requests.length ? (
            <div className="rb-list">
              {requests.map((req) => {
                const done = ["fulfilled", "completed", "denied"].includes(req.status?.toLowerCase());
                return (
                  <div className="rb-listrow" key={req.id} style={{ display: "block" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div className="rb-listrow__title" style={{ flex: 1 }}>
                        {req.recipient || "Recipient"} <span className="rb-muted">· #{req.id}</span>
                      </div>
                      <StatusBadge status={req.status} />
                    </div>
                    <div className="rb-listrow__meta" style={{ marginTop: 6 }}>
                      <span>{req.recipient_type}</span>
                      <span>{req.purpose}</span>
                      {(req.date_range_start || req.date_range_end) && (
                        <span>{fmtDate(req.date_range_start)} – {fmtDate(req.date_range_end)}</span>
                      )}
                    </div>
                    {!done && (
                      <div style={{ marginTop: 10 }}>
                        <button
                          className="rb-btn rb-btn--sm"
                          onClick={() => fulfill(req)}
                          disabled={busyFulfill === req.id}
                          type="button"
                        >
                          {busyFulfill === req.id ? "Fulfilling…" : "Fulfill"}
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="rb-empty">No release requests on file for this patient.</div>
          )}
        </Card>
      </div>
    </div>
  );
}
