import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import AssistantPage from "./page";

// RTL auto-cleanup is not registered without Vitest globals (e1 convention —
// tests import their own describe/it/expect), so it is explicit here.
afterEach(cleanup);

const apiFetch = vi.fn();
const clearSession = vi.fn();
const replace = vi.fn();

vi.mock("../lib/session", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
  clearSession: () => clearSession(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function okTurn(over: Record<string, unknown> = {}) {
  return jsonResponse(200, {
    visit_id: "a".repeat(32),
    visit_memory: "ok",
    reply: "Coverage is active with Aetna as of 2026-08-07.",
    disclaimer: "Verify with the payer before billing.",
    eligibility: { status: "active", payer: "Aetna", checked_at: "2026-08-07T10:00:00Z" },
    assistant: "ok",
    ...over,
  });
}

async function send(text: string) {
  fireEvent.change(screen.getByLabelText(/message/i), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /send/i }));
}

function lastBody(): Record<string, unknown> {
  const call = apiFetch.mock.calls[apiFetch.mock.calls.length - 1];
  return JSON.parse((call[1] as RequestInit).body as string);
}

beforeEach(() => {
  apiFetch.mockReset();
  clearSession.mockReset();
  replace.mockReset();
});

describe("assistant chat surface", () => {
  it("sends a message and renders the assistant's reply in the visit (W3-SPEC-20)", async () => {
    apiFetch.mockResolvedValueOnce(okTurn());
    render(<AssistantPage />);

    await send("Is this patient covered?");

    expect(await screen.findByText(/Coverage is active with Aetna/)).toBeInTheDocument();
    expect(screen.getByText("Is this patient covered?")).toBeInTheDocument();
    expect(screen.getByText(/Verify with the payer before billing/)).toBeInTheDocument();
    // The verdict tone rides along with the server-rendered prose.
    expect(screen.getByRole("status")).toHaveTextContent("Coverage active");
    expect(apiFetch).toHaveBeenCalledWith("/api/ai/visit-chat", expect.anything());
    // A first turn carries no visit_id — the gateway mints one.
    expect(lastBody()).toEqual({ message: "Is this patient covered?" });
  });

  it("echoes the visit id on the following turn (W3-SPEC-20)", async () => {
    apiFetch.mockResolvedValueOnce(okTurn());
    render(<AssistantPage />);

    await send("Is this patient covered?");
    await screen.findByText(/Coverage is active with Aetna/);

    apiFetch.mockResolvedValueOnce(okTurn({ reply: "Yes, still active." }));
    await send("Is it still active?");
    await screen.findByText("Yes, still active.");

    expect(lastBody()).toEqual({
      message: "Is it still active?",
      visit_id: "a".repeat(32),
    });
  });

  it("starts a fresh visit when the gateway returns a null visit id (W3-SPEC-20)", async () => {
    // visit_memory "unavailable": the id resolves to nothing, so echoing it back
    // would 404 the next turn with no explanation.
    apiFetch.mockResolvedValueOnce(
      okTurn({ visit_id: null, visit_memory: "unavailable" })
    );
    render(<AssistantPage />);

    await send("Is this patient covered?");
    await screen.findByText(/Coverage is active with Aetna/);

    apiFetch.mockResolvedValueOnce(okTurn({ reply: "Fresh visit." }));
    await send("Second message");
    await screen.findByText("Fresh visit.");

    expect(lastBody()).toEqual({ message: "Second message" });
  });

  // NEGATIVE (docs/landmines.md §3 — a coverage answer read under the wrong
  // context is the harm). The server dropped this visit; the transcript above
  // the seam is no longer anything the next turn can build on.
  it("marks the seam when the gateway returns no visit id (W3-SPEC-20)", async () => {
    apiFetch.mockResolvedValueOnce(
      okTurn({ visit_id: null, visit_memory: "unavailable" })
    );
    render(<AssistantPage />);

    await send("Is this patient covered?");
    await screen.findByText(/Coverage is active with Aetna/);

    expect(
      screen.getByText(/restate the patient and member details/i)
    ).toBeInTheDocument();
  });

  it("treats a degraded assistant as a successful turn, not an error (W3-SPEC-22)", async () => {
    apiFetch.mockResolvedValueOnce(
      okTurn({ assistant: "degraded", visit_memory: "stale" })
    );
    render(<AssistantPage />);

    await send("Is this patient covered?");

    expect(await screen.findByText(/Coverage is active with Aetna/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.getByText(/assistant is answering in a degraded mode/i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/may not have been saved to this visit/i)
    ).toBeInTheDocument();
  });

  // NEGATIVE (docs/landmines.md §3 — an unqualified answer read as a tailored
  // one is the harm). The gateway reports "unknown" when it could not recognise
  // ai-assistant's health field (rolling deploy, dropped field); collapsing that
  // into "ok" is the green-dashboard lie the tri-state exists to prevent.
  it("marks an unreported assistant mode instead of rendering it as normal (W3-SPEC-22)", async () => {
    apiFetch.mockResolvedValueOnce(okTurn({ assistant: "unknown" }));
    render(<AssistantPage />);

    await send("Is this patient covered?");

    // The turn still succeeds — the verdict was paid for by a real payer call.
    expect(await screen.findByText(/Coverage is active with Aetna/)).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Coverage active");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    // ...but it is not presented as a normal one.
    expect(screen.getByText(/did not report how it produced this reply/i)).toBeInTheDocument();
    // Not the degraded wording: claiming a checklist we cannot confirm would be
    // a false alarm on every turn of a rolling deploy (gateway app.py:1180).
    expect(
      screen.queryByText(/assistant is answering in a degraded mode/i)
    ).not.toBeInTheDocument();
  });

  it("marks neither mode on a healthy turn (W3-SPEC-22)", async () => {
    apiFetch.mockResolvedValueOnce(okTurn());
    render(<AssistantPage />);

    await send("Is this patient covered?");
    await screen.findByText(/Coverage is active with Aetna/);

    expect(screen.queryByText(/did not report how it produced this reply/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/assistant is answering in a degraded mode/i)
    ).not.toBeInTheDocument();
  });

  // NEGATIVE (docs/landmines.md §3 — authz path). The gateway is the only
  // enforcement point; the surface must state the refusal and stop asking.
  it("stops the conversation on a 403 and never retries (W3-SPEC-21)", async () => {
    apiFetch.mockResolvedValueOnce(
      jsonResponse(403, { detail: "role clinician lacks capability ai.use" })
    );
    render(<AssistantPage />);

    await send("Is this patient covered?");

    expect(
      await screen.findByText("Your role isn't authorized for eligibility work.")
    ).toBeInTheDocument();
    // The gateway's own words never reach the screen.
    expect(screen.queryByText(/lacks capability/)).not.toBeInTheDocument();

    const box = screen.getByLabelText(/message/i);
    expect(box).toBeDisabled();
    expect(screen.getByRole("button", { name: /send/i })).toBeDisabled();

    fireEvent.change(box, { target: { value: "please?" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(1));
  });

  it("clears the session and returns to login on a 401 (W3-SPEC-21)", async () => {
    apiFetch.mockResolvedValueOnce(jsonResponse(401, { detail: "invalid session" }));
    render(<AssistantPage />);

    await send("Is this patient covered?");

    await waitFor(() => expect(clearSession).toHaveBeenCalled());
    expect(replace).toHaveBeenCalledWith("/login");
    expect(screen.queryByText(/invalid session/)).not.toBeInTheDocument();
  });

  // NEGATIVE (docs/landmines.md §3). A raw upstream error is the leak class —
  // it can carry a payer host, an internal URL, or the clerk's own text back.
  it("shows a deterministic fallback on a 503, never the server's text (W3-SPEC-22)", async () => {
    apiFetch.mockResolvedValueOnce(
      jsonResponse(503, { detail: "assistant is temporarily unavailable: redis://cache:6379" })
    );
    render(<AssistantPage />);

    await send("Is this patient covered?");

    expect(
      await screen.findByText(
        "The assistant is unavailable right now. Coverage can still be checked directly with the payer."
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/redis:\/\//)).not.toBeInTheDocument();
    expect(screen.queryByText(/temporarily unavailable/)).not.toBeInTheDocument();
  });

  it("shows the same fallback when the request never completes (W3-SPEC-22)", async () => {
    apiFetch.mockRejectedValueOnce(new Error("fetch failed: connect ECONNREFUSED 10.0.0.7:8070"));
    render(<AssistantPage />);

    await send("Is this patient covered?");

    expect(
      await screen.findByText(
        "The assistant is unavailable right now. Coverage can still be checked directly with the payer."
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/ECONNREFUSED/)).not.toBeInTheDocument();
  });

  it("shows the fallback when a 200 body is not the expected shape (W3-SPEC-22)", async () => {
    apiFetch.mockResolvedValueOnce(jsonResponse(200, { error: "gateway unreachable" }));
    render(<AssistantPage />);

    await send("Is this patient covered?");

    expect(
      await screen.findByText(
        "The assistant is unavailable right now. Coverage can still be checked directly with the payer."
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/gateway unreachable/)).not.toBeInTheDocument();
  });

  it("drops an expired visit and keeps the surface usable on a 404 (W3-SPEC-22)", async () => {
    apiFetch.mockResolvedValueOnce(okTurn());
    render(<AssistantPage />);
    await send("Is this patient covered?");
    await screen.findByText(/Coverage is active with Aetna/);

    apiFetch.mockResolvedValueOnce(jsonResponse(404, { detail: "visit not found" }));
    await send("Is it still active?");
    expect(
      await screen.findByText("That conversation has expired — starting a new one.")
    ).toBeInTheDocument();

    // The prior answer stays readable, but a seam separates it from anything
    // the new visit says — the gateway holds none of it.
    expect(
      screen.getByText(/restate the patient and member details/i)
    ).toBeInTheDocument();
    expect(screen.getByText(/Coverage is active with Aetna/)).toBeInTheDocument();

    apiFetch.mockResolvedValueOnce(okTurn({ reply: "Fresh visit." }));
    await send("Is it still active?");
    await screen.findByText("Fresh visit.");
    expect(lastBody()).toEqual({ message: "Is it still active?" });
  });

  // NEGATIVE (docs/landmines.md §3). A 200 carrying `reply` but no disclaimer,
  // no verdict and no memory state would render as a verified coverage answer
  // stripped of everything that qualifies it.
  it.each([
    ["no disclaimer", { disclaimer: undefined }],
    ["no visit_memory", { visit_memory: undefined }],
    ["no assistant state", { assistant: undefined }],
    ["no eligibility key", { eligibility: undefined }],
    ["an unrecognised visit_memory", { visit_memory: "lost" }],
    ["an unrecognised assistant state", { assistant: "hallucinating" }],
    ["a visit id of the wrong shape", { visit_id: "not-a-visit-id" }],
    ["a non-object eligibility", { eligibility: "active" }],
  ])("falls back on a 200 with %s (W3-SPEC-22)", async (_name, over) => {
    apiFetch.mockResolvedValueOnce(okTurn(over));
    render(<AssistantPage />);

    await send("Is this patient covered?");

    expect(
      await screen.findByText(
        "The assistant is unavailable right now. Coverage can still be checked directly with the payer."
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/Coverage is active with Aetna/)).not.toBeInTheDocument();
  });

  it("names the retry path on a 429 rather than failing the visit (W3-SPEC-22)", async () => {
    apiFetch.mockResolvedValueOnce(jsonResponse(429, { detail: "already processing" }));
    render(<AssistantPage />);

    await send("Is this patient covered?");

    expect(
      await screen.findByText("The assistant is busy — try again in a moment.")
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/message/i)).not.toBeDisabled();
  });
});
