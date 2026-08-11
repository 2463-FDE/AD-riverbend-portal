import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import AppointmentsPage from "./page";

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

const APPTS_EMPTY = "No appointments for this patient yet.";
const SLOTS_EMPTY = "No open slots available right now.";

const OK_APPTS = jsonResponse(200, { items: [] });
const OK_SLOTS = jsonResponse(200, { items: [] });

// The page fires both reads from one effect, appointments first.
function respond(appts: Response, slots: Response) {
  apiFetch.mockResolvedValueOnce(appts).mockResolvedValueOnce(slots);
}

beforeEach(() => {
  apiFetch.mockReset();
});

describe("appointment list read surface (E5-SPEC-5 .. E5-SPEC-8)", () => {
  it("renders a failed load, not an empty list, on a gateway failure status", async () => {
    respond(jsonResponse(503, { detail: "scheduling service unreachable" }), OK_SLOTS);
    render(<AppointmentsPage />);

    expect(await screen.findByText(/appointments could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(APPTS_EMPTY)).toBeNull();
  });

  it("renders a failed load when a 200 body is not the expected shape", async () => {
    respond(jsonResponse(200, { detail: "scheduling service error" }), OK_SLOTS);
    render(<AppointmentsPage />);

    expect(await screen.findByText(/appointments could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(APPTS_EMPTY)).toBeNull();
  });

  it("still renders the empty state when there are genuinely no appointments", async () => {
    respond(OK_APPTS, OK_SLOTS);
    render(<AppointmentsPage />);

    expect(await screen.findByText(APPTS_EMPTY)).toBeInTheDocument();
    expect(screen.queryByText(/appointments could not be loaded/i)).toBeNull();
  });
});

describe("bookable-slots read surface (E5-SPEC-5 .. E5-SPEC-8)", () => {
  it("renders a failed load, not 'no open slots', on a gateway failure status", async () => {
    // The one that misinforms a patient rather than an operator: "no open
    // slots" sends someone away from a clinic that has availability.
    respond(OK_APPTS, jsonResponse(502, { detail: "scheduling service unreachable" }));
    render(<AppointmentsPage />);

    expect(await screen.findByText(/open slots could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(SLOTS_EMPTY)).toBeNull();
  });

  it("renders a failed load when a 200 body is not the expected shape", async () => {
    respond(OK_APPTS, jsonResponse(200, { detail: "scheduling service error" }));
    render(<AppointmentsPage />);

    expect(await screen.findByText(/open slots could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(SLOTS_EMPTY)).toBeNull();
  });

  it("still renders the empty state when there are genuinely no open slots", async () => {
    respond(OK_APPTS, OK_SLOTS);
    render(<AppointmentsPage />);

    expect(await screen.findByText(SLOTS_EMPTY)).toBeInTheDocument();
    expect(screen.queryByText(/open slots could not be loaded/i)).toBeNull();
  });

  it("renders the slots when the read succeeds", async () => {
    respond(
      OK_APPTS,
      jsonResponse(200, {
        items: [
          {
            id: 4,
            provider: "Dr. Patel",
            status: "open",
            start_at: "2026-09-01T15:00:00Z",
            end_at: "2026-09-01T15:30:00Z",
          },
        ],
      })
    );
    render(<AppointmentsPage />);

    expect(await screen.findByText("Dr. Patel")).toBeInTheDocument();
    expect(screen.queryByText(SLOTS_EMPTY)).toBeNull();
    expect(screen.queryByText(/could not be loaded/i)).toBeNull();
  });
});
