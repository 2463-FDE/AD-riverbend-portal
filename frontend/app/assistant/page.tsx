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

interface Turn {
  role: "user" | "assistant";
  text: string;
  disclaimer?: string;
  eligibility?: EligibilityVerdict | null;
  degraded?: boolean;
  stale?: boolean;
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
        // lets the next message open a fresh one.
        setVisitId(null);
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
      // Shape check before anything is rendered: `proxy` answers 200 for a
      // gateway body it could not parse, and gateway `_post` (not this route,
      // but the house pattern) answers 200 with an {"error": …} body.
      if (typeof data?.reply !== "string") {
        setNotice(FALLBACK);
        return;
      }
      // A null id means the write did not land — echoing it back would 404 the
      // next turn with no explanation, so let that turn start a fresh visit.
      setVisitId(typeof data.visit_id === "string" ? data.visit_id : null);
      setTurns((t) => [
        ...t,
        {
          role: "assistant",
          text: data.reply as string,
          disclaimer: typeof data.disclaimer === "string" ? data.disclaimer : undefined,
          eligibility: data.eligibility ?? null,
          // Both are honest degradations riding a SUCCESSFUL turn — the clerk
          // has a real answer. Rendering them as errors would train the desk to
          // ignore the surface on the days it matters most.
          degraded: data.assistant === "degraded",
          stale: data.visit_memory === "stale",
        },
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
          {turns.map((turn, i) => (
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
              {turn.degraded && (
                <div className="rb-alert rb-alert--info" style={{ marginTop: 8 }}>
                  The assistant is answering in a degraded mode — this reply is a standard
                  checklist rather than a tailored one. The coverage verdict above is
                  unaffected.
                </div>
              )}
              {turn.stale && (
                <div className="rb-alert rb-alert--info" style={{ marginTop: 8 }}>
                  This turn may not have been saved to this visit&apos;s context — a
                  follow-up question may need restating in full.
                </div>
              )}
            </div>
          ))}
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
