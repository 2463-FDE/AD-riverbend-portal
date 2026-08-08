"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Card from "../components/Card";
import VerdictBadge from "../components/VerdictBadge";
import { apiFetch, clearSession } from "../lib/session";
import type { EligibilityVerdict, VisitChatResponse } from "../lib/types";

// Every string the surface can show on a failure is fixed, client-authored and
// non-PHI (W3-SPEC-22). The upstream body is never read on a non-2xx path at
// all — not rendered, not logged — so there is no route by which a payer host,
// an internal URL, or the clerk's own text comes back through an error.
const FALLBACK =
  "The assistant is unavailable right now. Coverage can still be checked directly with the payer.";
const NOT_AUTHORIZED = "Your role isn't authorized for eligibility work.";
const EXPIRED = "That conversation has expired — starting a new one.";
const BUSY = "The assistant is busy — try again in a moment.";

// Mirrors the gateway's AI_VISIT_MAX_MESSAGE_CHARS default
// (services/gateway/config.py:153). An UNPINNED mirror, accepted deliberately:
// if the operator raises the gateway bound this cap is merely conservative, and
// if they lower it the cost is a handled 422 rendered as FALLBACK — not a
// broken surface. A client-side copy of the role map would not be so cheap,
// which is why there isn't one (W3-SPEC-21 is enforced gateway-side only).
const MAX_MESSAGE_CHARS = 1000;

// The id the gateway mints (services/gateway/security.py:649) and pins on the
// way in (app.py:711). Validated on the way out too: an id of any other shape
// cannot be echoed back successfully, so accepting one only buys a 404 later.
const VISIT_ID = /^[0-9a-f]{32}$/;

// A "boundary" carries no prose — it is the visible seam where the server lost
// this visit's context. Without it the transcript reads as one continuous
// conversation while the gateway has already started a second, empty one, and
// the clerk mixes a stale payer answer with a contextless follow-up.
interface Turn {
  role: "user" | "assistant" | "boundary";
  text: string;
  disclaimer?: string;
  eligibility?: EligibilityVerdict | null;
  // Carried as the gateway's tri-state, not as a boolean. "unknown" is not a
  // quieter "degraded" and it is certainly not "ok": it means the gateway could
  // not recognise ai-assistant's health field at all (app.py:1180). Flattening
  // it either way is a claim the server explicitly refused to make.
  assistant?: VisitChatResponse["assistant"];
  stale?: boolean;
}

const BOUNDARY: Turn = { role: "boundary", text: "" };

// The verdict's own fields, checked to their declared types (app/lib/types.ts
// EligibilityVerdict). `status` is the one the badge reads, and the other three
// are what stamps an answer with a payer and a time. UNKNOWN EXTRA KEYS PASS on
// purpose: the gateway adding a field must not blank the surface — only a known
// field carrying the wrong type is a contract break.
const VERDICT_STRINGS = ["status", "payer", "checked_at", "observed_at"] as const;

function isVerdict(v: Record<string, unknown>): boolean {
  if (v.active !== undefined && v.active !== null && typeof v.active !== "boolean") return false;
  return VERDICT_STRINGS.every(
    (k) => v[k] === undefined || v[k] === null || typeof v[k] === "string"
  );
}

// The full 200 contract, not just `reply` (W3-SPEC-22). `proxy` answers 200 for
// a body it could not parse and gateway `_post` answers 200 with {"error": …},
// so a partial body is reachable under version skew or a misrouted response.
// Rendering one would drop the disclaimer and the verdict — the two things that
// separate a verified coverage answer from unqualified assistant prose.
function isVisitChat(d: Partial<VisitChatResponse> | null): d is VisitChatResponse {
  if (!d || typeof d !== "object") return false;
  if (typeof d.reply !== "string" || typeof d.disclaimer !== "string") return false;
  if (d.visit_id !== null && !(typeof d.visit_id === "string" && VISIT_ID.test(d.visit_id)))
    return false;
  if (d.visit_memory !== "ok" && d.visit_memory !== "stale" && d.visit_memory !== "unavailable")
    return false;
  if (d.assistant !== "ok" && d.assistant !== "degraded" && d.assistant !== "unknown")
    return false;
  if (d.eligibility !== null) {
    if (typeof d.eligibility !== "object" || Array.isArray(d.eligibility)) return false;
    // A verdict of the wrong inner shape is a contract break like any other
    // here, not a field to render around: the guard's whole job is that what it
    // hands the render path is what the type says it is.
    if (!isVerdict(d.eligibility as Record<string, unknown>)) return false;
  }
  return true;
}

export default function AssistantPage() {
  const router = useRouter();
  // The transcript is render-only and lives for as long as this page is open.
  // The gateway persists METADATA ONLY (ADR 0011 §3) and never the prose, so
  // there is nothing to reload — a refresh legitimately starts a blank screen
  // on a visit the gateway still remembers.
  const [turns, setTurns] = useState<Turn[]>([]);
  const [visitId, setVisitId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // A 403 is a property of the session's role, not of the message: retrying
  // spends the clerk's time and the gateway's rate limit to be refused again.
  const [blocked, setBlocked] = useState(false);

  function failed(status: number): string | null {
    switch (status) {
      case 401:
        // Same handling as AppShell's no-token path.
        clearSession();
        router.replace("/login");
        return null;
      case 403:
        setBlocked(true);
        return NOT_AUTHORIZED;
      case 404:
        // The gateway answers 404 for both "expired" and "not yours" so that a
        // status cannot confirm someone else's visit exists. Dropping the id
        // lets the next message open a fresh one — and the boundary keeps the
        // clerk from reading that fresh one as a continuation of what is still
        // on screen, since the server no longer holds any of it.
        setVisitId(null);
        setTurns((t) => [...t, BOUNDARY]);
        return EXPIRED;
      case 429:
        return BUSY;
      default:
        return FALLBACK;
    }
  }

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const message = input.trim();
    if (!message || busy || blocked) return;

    setNotice(null);
    setBusy(true);
    setTurns((t) => [...t, { role: "user", text: message }]);
    setInput("");

    try {
      const res = await apiFetch("/api/ai/visit-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, ...(visitId ? { visit_id: visitId } : {}) }),
      });
      if (!res.ok) {
        setNotice(failed(res.status));
        return;
      }
      const data = (await res.json()) as Partial<VisitChatResponse>;
      if (!isVisitChat(data)) {
        setNotice(FALLBACK);
        return;
      }
      // A null id means the write did not land — echoing it back would 404 the
      // next turn with no explanation, so let that turn start a fresh visit.
      // Same seam as the 404: the answer just given used the context that was
      // sent, but nothing after it will, so the transcript says so.
      const carriesOn = data.visit_id !== null;
      setVisitId(data.visit_id);
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          text: data.reply,
          disclaimer: data.disclaimer,
          eligibility: data.eligibility,
          // Both are honest degradations riding a SUCCESSFUL turn — the clerk
          // has a real answer. Rendering them as errors would train the desk to
          // ignore the surface on the days it matters most.
          assistant: data.assistant,
          stale: data.visit_memory === "stale",
        },
        ...(carriesOn ? [] : [BOUNDARY]),
      ]);
    } catch {
      setNotice(FALLBACK);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rb-stack">
      <div className="rb-page-head">
        <h1>Eligibility Assistant</h1>
        <p>
          Ask about a patient&apos;s insurance coverage for this visit. Answers come from a
          live payer check — the assistant never decides coverage itself.
        </p>
      </div>

      <Card title="Visit conversation">
        <div role="log" aria-live="polite" aria-label="Conversation">
          {turns.length === 0 && (
            <p className="rb-muted">
              No messages yet. Ask about a patient&apos;s coverage to start this visit&apos;s
              conversation.
            </p>
          )}
          {turns.map((turn, i) =>
            turn.role === "boundary" ? (
              <div key={i} className="rb-alert rb-alert--warn" style={{ marginBottom: 18 }}>
                New conversation starts here. The assistant no longer has anything above this
                line — restate the patient and member details in your next message.
              </div>
            ) : (
            <div key={i} style={{ marginBottom: 18 }}>
              <div className="rb-field__hint" style={{ marginBottom: 4 }}>
                {turn.role === "user" ? "You" : "Assistant"}
              </div>
              <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{turn.text}</p>
              {turn.eligibility && (
                <div style={{ marginTop: 8 }}>
                  <VerdictBadge eligibility={turn.eligibility} />
                </div>
              )}
              {turn.disclaimer && (
                <p className="rb-muted" style={{ marginTop: 8, fontSize: "0.82rem" }}>
                  {turn.disclaimer}
                </p>
              )}
              {turn.assistant === "degraded" && (
                <div className="rb-alert rb-alert--info" style={{ marginTop: 8 }}>
                  The assistant is answering in a degraded mode — this reply is a standard
                  checklist rather than a tailored one. The coverage verdict above is
                  unaffected.
                </div>
              )}
              {turn.assistant === "unknown" && (
                <div className="rb-alert rb-alert--info" style={{ marginTop: 8 }}>
                  The assistant did not report how it produced this reply, so treat its
                  wording as unconfirmed — it may be a standard checklist rather than a
                  tailored one. The coverage verdict above is unaffected.
                </div>
              )}
              {turn.stale && (
                <div className="rb-alert rb-alert--info" style={{ marginTop: 8 }}>
                  This turn may not have been saved to this visit&apos;s context — a
                  follow-up question may need restating in full.
                </div>
              )}
            </div>
            )
          )}
        </div>

        {notice && (
          <div className="rb-alert rb-alert--err" role="alert">
            {notice}
          </div>
        )}

        <form onSubmit={send}>
          <div className="rb-field">
            <label className="rb-field__label" htmlFor="assistant-message">
              Message
            </label>
            <textarea
              id="assistant-message"
              className="rb-textarea"
              value={input}
              maxLength={MAX_MESSAGE_CHARS}
              disabled={blocked}
              placeholder="e.g. Does this patient have active coverage today?"
              onChange={(e) => setInput(e.target.value)}
            />
            <span className="rb-field__hint">
              Coverage answers are payer-sourced. Anything the assistant cannot verify is
              shown as unverified, never as a denial.
            </span>
          </div>
          <div className="rb-wizard-actions">
            <button
              className="rb-btn rb-btn--primary"
              type="submit"
              disabled={busy || blocked || !input.trim()}
            >
              {busy ? (
                <>
                  <span className="rb-spinner" aria-hidden="true" /> Asking the assistant…
                </>
              ) : (
                "Send"
              )}
            </button>
          </div>
        </form>
      </Card>
    </div>
  );
}
