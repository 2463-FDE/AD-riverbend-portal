"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Card from "../components/Card";
import { apiFetch, clearSession } from "../lib/session";
import type { Disposition, ReviewQueueItem, ReviewQueueResponse } from "../lib/types";
import { fmtDate } from "../lib/format";

// Every failure string is fixed, client-authored and non-PHI. The upstream body
// is never read on a non-2xx path, so no downstream URL, database error, or
// patient value can come back through an error notice.
const FALLBACK = "The review queue is unavailable right now. Try again shortly.";
const NOT_AUTHORIZED = "Your role isn't authorized for duplicate review.";
const GONE = "Someone else already recorded a decision on that pair.";
const MISSING = "That pair is no longer in the queue.";

function isQueue(d: unknown): d is ReviewQueueResponse {
  if (!d || typeof d !== "object") return false;
  const items = (d as ReviewQueueResponse).items;
  if (!Array.isArray(items)) return false;
  return items.every(
    (i) =>
      i &&
      typeof i === "object" &&
      typeof i.id === "number" &&
      typeof i.source === "string" &&
      isPatient(i.patient_a) &&
      isPatient(i.patient_b)
  );
}

function isPatient(p: unknown): boolean {
  return Boolean(
    p && typeof p === "object" &&
      typeof (p as { id: unknown }).id === "number" &&
      typeof (p as { name: unknown }).name === "string"
  );
}

export default function ReviewQueuePage() {
  const router = useRouter();
  const [items, setItems] = useState<ReviewQueueItem[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // A 403 is a property of the session's role, not of the request: retrying
  // only spends the reviewer's time to be refused again.
  const [blocked, setBlocked] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  // useRouter() hands back a fresh object on every render. Depending on it
  // directly would give `failed` — and through it `load` — a new identity each
  // render, and the mount effect below would re-fetch the queue every time the
  // component re-rendered. Hold the router behind a ref so the callbacks are
  // stable and the queue is read once.
  const routerRef = useRef(router);
  useEffect(() => {
    routerRef.current = router;
  }, [router]);

  const failed = useCallback((status: number): string | null => {
    switch (status) {
      case 401:
        // Same handling as AppShell's no-token path.
        clearSession();
        routerRef.current.replace("/login");
        return null;
      case 403:
        setBlocked(true);
        return NOT_AUTHORIZED;
      case 404:
        return MISSING;
      case 409:
        return GONE;
      default:
        return FALLBACK;
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch("/api/review-queue");
      if (!res.ok) {
        setNotice(failed(res.status));
        setItems([]);
        return;
      }
      const data: unknown = await res.json();
      if (!isQueue(data)) {
        setNotice(FALLBACK);
        setItems([]);
        return;
      }
      setItems(data.items);
    } catch {
      setNotice(FALLBACK);
      setItems([]);
    }
  }, [failed]);

  useEffect(() => {
    void load();
  }, [load]);

  async function decide(pairId: number, disposition: Disposition) {
    if (busyId !== null || blocked) return;
    setBusyId(pairId);
    setNotice(null);
    try {
      const res = await apiFetch(`/api/review-queue/${pairId}/disposition`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // No decided_by: the gateway stamps it from the session, and a value
        // sent here would be discarded there anyway.
        body: JSON.stringify({ disposition }),
      });
      if (!res.ok) {
        setNotice(failed(res.status));
        // A 404/409 means someone else moved this pair — the list on screen is
        // stale, so re-read it rather than leaving a row that cannot be acted on.
        if (res.status === 404 || res.status === 409) await load();
        return;
      }
      setItems((current) => (current ?? []).filter((i) => i.id !== pairId));
    } catch {
      setNotice(FALLBACK);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="rb-stack">
      <div className="rb-page-head">
        <h1>Duplicate Review</h1>
        <p>
          Charts that may belong to the same person, flagged at registration or by a
          retroactive pass. Recording a decision here documents your judgment — it does not
          merge, change, or delete either chart. Merging remains a Health Information
          Management procedure.
        </p>
      </div>

      {notice && (
        <div className="rb-alert rb-alert--err" role="alert">
          {notice}
        </div>
      )}

      <Card title="Pending pairs">
        {items === null && <p className="rb-muted">Loading the review queue…</p>}
        {items !== null && items.length === 0 && !blocked && (
          <div className="rb-empty">No pairs are waiting for review.</div>
        )}
        {items !== null && items.length > 0 && (
          <div className="rb-list">
            {items.map((item) => (
              <div key={item.id} className="rb-listrow" style={{ display: "block" }}>
                <div className="rb-grid rb-grid--2">
                  <PatientColumn label="Chart A" patient={item.patient_a} />
                  <PatientColumn label="Chart B" patient={item.patient_b} />
                </div>
                <div className="rb-listrow__meta" style={{ marginTop: 8 }}>
                  <span>Flagged by: {item.source === "intake" ? "registration" : "retroactive pass"}</span>
                  {item.created_at && <span>{fmtDate(item.created_at)}</span>}
                </div>
                <div className="rb-wizard-actions" style={{ marginTop: 10 }}>
                  <button
                    className="rb-btn rb-btn--primary"
                    type="button"
                    disabled={busyId !== null || blocked}
                    onClick={() => decide(item.id, "duplicate_confirmed")}
                  >
                    Same person
                  </button>
                  <button
                    className="rb-btn"
                    type="button"
                    disabled={busyId !== null || blocked}
                    onClick={() => decide(item.id, "not_duplicate")}
                  >
                    Different people
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function PatientColumn({
  label,
  patient,
}: {
  label: string;
  patient: ReviewQueueItem["patient_a"];
}) {
  return (
    <div>
      <div className="rb-field__hint">{label}</div>
      <div className="rb-listrow__title">{patient.name}</div>
      <div className="rb-listrow__meta">
        <span>ID {patient.id}</span>
        {patient.dob && <span>DOB {patient.dob}</span>}
        {patient.created_via && <span>via {patient.created_via}</span>}
      </div>
    </div>
  );
}
