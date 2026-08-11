import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import RoiPage from "./page";

// RTL auto-cleanup is not registered without Vitest globals (e1 convention —
// tests import their own describe/it/expect), so it is explicit here.
afterEach(cleanup);

const apiFetch = vi.fn();

vi.mock("../lib/session", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
}));

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const EMPTY_COPY = "No release requests on file for this patient.";

beforeEach(() => {
  apiFetch.mockReset();
});

describe("ROI queue read surface (E5-SPEC-5 .. E5-SPEC-8)", () => {
  it("renders a failed load, not an empty queue, on a gateway failure status", async () => {
    apiFetch.mockResolvedValueOnce(jsonResponse(503, { detail: "roi service unreachable" }));
    render(<RoiPage />);

    expect(await screen.findByText(/release requests could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_COPY)).toBeNull();
  });

  it("renders a failed load when a 200 body is not the expected shape", async () => {
    // A converted gateway sends {"detail": ...}, which is as non-list as the
    // {"error": ...} body the swallowing helpers sent. `d.items ?? []` coerced
    // both to "you have none" — which is why the gateway conversion alone does
    // not close this defect.
    apiFetch.mockResolvedValueOnce(jsonResponse(200, { detail: "roi service error" }));
    render(<RoiPage />);

    expect(await screen.findByText(/release requests could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_COPY)).toBeNull();
  });

  it("still renders the empty state when the queue is genuinely empty", async () => {
    apiFetch.mockResolvedValueOnce(jsonResponse(200, { items: [] }));
    render(<RoiPage />);

    expect(await screen.findByText(EMPTY_COPY)).toBeInTheDocument();
    expect(screen.queryByText(/could not be loaded/i)).toBeNull();
  });

  it("renders the requests when the read succeeds", async () => {
    apiFetch.mockResolvedValueOnce(
      jsonResponse(200, [
        { id: 7, recipient: "Dr Vance", recipient_type: "Healthcare provider", status: "pending" },
      ])
    );
    render(<RoiPage />);

    expect(await screen.findByText(/Dr Vance/)).toBeInTheDocument();
    expect(screen.queryByText(/could not be loaded/i)).toBeNull();
    expect(screen.queryByText(EMPTY_COPY)).toBeNull();
  });
});
