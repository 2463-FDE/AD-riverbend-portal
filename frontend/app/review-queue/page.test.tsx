import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import ReviewQueuePage from "./page";

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

const PAIR = {
  id: 7,
  patient_a: { id: 1042, name: "Maria Gonzalez", dob: "1971-03-02", created_via: "self_service" },
  patient_b: { id: 1330, name: "Maria Gonzales", dob: "1971-03-02", created_via: "self_service" },
  source: "retroactive",
  created_at: "2026-08-08T09:00:00Z",
};

function queue(items: unknown[] = [PAIR]) {
  return jsonResponse(200, { items });
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

describe("duplicate review queue surface", () => {
  it("lists the pending pairs with both charts (W2-SPEC-25)", async () => {
    apiFetch.mockResolvedValueOnce(queue());
    render(<ReviewQueuePage />);

    expect(await screen.findByText("Maria Gonzalez")).toBeInTheDocument();
    expect(screen.getByText("Maria Gonzales")).toBeInTheDocument();
    expect(screen.getByText("ID 1042")).toBeInTheDocument();
    expect(screen.getByText("ID 1330")).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith("/api/review-queue");
  });

  it("states that a decision is not a merge (ADR 0005 decision 3)", async () => {
    apiFetch.mockResolvedValueOnce(queue());
    render(<ReviewQueuePage />);
    await screen.findByText("Maria Gonzalez");
    expect(
      screen.getByText(/does not merge, change, or delete either chart/i)
    ).toBeInTheDocument();
  });

  it("records a disposition and drops the pair from the list (W2-SPEC-26)", async () => {
    apiFetch
      .mockResolvedValueOnce(queue())
      .mockResolvedValueOnce(jsonResponse(200, { id: 7, status: "dispositioned" }));
    render(<ReviewQueuePage />);
    await screen.findByText("Maria Gonzalez");

    fireEvent.click(screen.getByRole("button", { name: /same person/i }));

    await waitFor(() => expect(screen.queryByText("Maria Gonzalez")).not.toBeInTheDocument());
    expect(apiFetch).toHaveBeenLastCalledWith(
      "/api/review-queue/7/disposition",
      expect.objectContaining({ method: "POST" })
    );
    expect(lastBody()).toEqual({ disposition: "duplicate_confirmed" });
  });

  it("never sends decided_by from the client", async () => {
    // The deciding username is the record of who judged two charts to be one
    // person. It comes from the session at the gateway; the browser must not
    // supply a value that could shadow it.
    apiFetch
      .mockResolvedValueOnce(queue())
      .mockResolvedValueOnce(jsonResponse(200, { id: 7, status: "dispositioned" }));
    render(<ReviewQueuePage />);
    await screen.findByText("Maria Gonzalez");

    fireEvent.click(screen.getByRole("button", { name: /different people/i }));

    await waitFor(() => expect(apiFetch).toHaveBeenCalledTimes(2));
    expect(lastBody()).not.toHaveProperty("decided_by");
    expect(lastBody()).toEqual({ disposition: "not_duplicate" });
  });

  it("shows a fixed notice and no upstream text when the queue fails to load", async () => {
    apiFetch.mockResolvedValueOnce(
      jsonResponse(503, { detail: "could not connect to intake-service:8071" })
    );
    render(<ReviewQueuePage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/review queue is unavailable/i);
    expect(screen.queryByText(/intake-service:8071/)).not.toBeInTheDocument();
  });

  it("shows a fixed notice when the response does not match the contract", async () => {
    apiFetch.mockResolvedValueOnce(jsonResponse(200, { items: [{ id: "seven" }] }));
    render(<ReviewQueuePage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/review queue is unavailable/i);
  });

  it("clears the session and redirects on 401", async () => {
    apiFetch.mockResolvedValueOnce(jsonResponse(401, { detail: "not authenticated" }));
    render(<ReviewQueuePage />);
    await waitFor(() => expect(clearSession).toHaveBeenCalled());
    expect(replace).toHaveBeenCalledWith("/login");
  });

  it("blocks the surface on 403 rather than inviting a retry (W2-SPEC-28)", async () => {
    apiFetch.mockResolvedValueOnce(
      jsonResponse(403, { detail: "requires capability patients.write" })
    );
    render(<ReviewQueuePage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/isn't authorized/i);
    // The gateway's capability name is an internal identifier, not something to
    // put in front of a front-desk user.
    expect(screen.queryByText(/patients.write/)).not.toBeInTheDocument();
  });

  it("re-reads the queue when a pair was already dispositioned elsewhere", async () => {
    apiFetch
      .mockResolvedValueOnce(queue())
      .mockResolvedValueOnce(jsonResponse(409, { detail: "review pair already dispositioned" }))
      .mockResolvedValueOnce(queue([]));
    render(<ReviewQueuePage />);
    await screen.findByText("Maria Gonzalez");

    fireEvent.click(screen.getByRole("button", { name: /same person/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already recorded a decision/i);
    await waitFor(() => expect(screen.queryByText("Maria Gonzalez")).not.toBeInTheDocument());
    expect(apiFetch).toHaveBeenCalledTimes(3);
  });

  it("renders an empty queue as empty, not as a failure", async () => {
    apiFetch.mockResolvedValueOnce(queue([]));
    render(<ReviewQueuePage />);
    expect(await screen.findByText(/no pairs are waiting for review/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
