import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import DashboardPage from "./page";

// RTL auto-cleanup is not registered without Vitest globals (e1 convention —
// tests import their own describe/it/expect), so it is explicit here.
afterEach(cleanup);

const apiFetch = vi.fn();

vi.mock("./lib/session", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
  getUser: () => ({ username: "frontdesk", full_name: "Dana Ruiz", role: "front_desk" }),
}));

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const APPTS_EMPTY = "No upcoming appointments.";
const RESULTS_EMPTY = "No recent lab results on file.";

const OK_APPTS = jsonResponse(200, { items: [] });
const OK_RECORDS = jsonResponse(200, { encounters: [] });

// One effect fires both reads, appointments first.
function respond(appts: Response, records: Response) {
  apiFetch.mockResolvedValueOnce(appts).mockResolvedValueOnce(records);
}

beforeEach(() => {
  apiFetch.mockReset();
});

describe("dashboard appointments panel (E5-SPEC-5 .. E5-SPEC-8)", () => {
  it("renders a failed load, not 'no upcoming appointments', on a failure status", async () => {
    respond(jsonResponse(504, { detail: "scheduling service timed out" }), OK_RECORDS);
    render(<DashboardPage />);

    expect(await screen.findByText(/appointments could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(APPTS_EMPTY)).toBeNull();
  });

  it("renders a failed load when a 200 body is not the expected shape", async () => {
    respond(jsonResponse(200, { detail: "scheduling service error" }), OK_RECORDS);
    render(<DashboardPage />);

    expect(await screen.findByText(/appointments could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(APPTS_EMPTY)).toBeNull();
  });

  it("still renders the empty state when there are genuinely none", async () => {
    respond(OK_APPTS, OK_RECORDS);
    render(<DashboardPage />);

    expect(await screen.findByText(APPTS_EMPTY)).toBeInTheDocument();
    expect(screen.queryByText(/appointments could not be loaded/i)).toBeNull();
  });
});

describe("dashboard results panel (E5-SPEC-5 .. E5-SPEC-8)", () => {
  it("renders a failed load, not 'no recent lab results', on a failure status", async () => {
    respond(OK_APPTS, jsonResponse(503, { detail: "records service unreachable" }));
    render(<DashboardPage />);

    expect(await screen.findByText(/recent results could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(RESULTS_EMPTY)).toBeNull();
  });

  it("renders a failed load when a 200 body carries no encounters array", async () => {
    respond(OK_APPTS, jsonResponse(200, { detail: "records service error" }));
    render(<DashboardPage />);

    expect(await screen.findByText(/recent results could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(RESULTS_EMPTY)).toBeNull();
  });

  it("still renders the empty state when there are genuinely no results", async () => {
    respond(OK_APPTS, OK_RECORDS);
    render(<DashboardPage />);

    expect(await screen.findByText(RESULTS_EMPTY)).toBeInTheDocument();
    expect(screen.queryByText(/recent results could not be loaded/i)).toBeNull();
  });

  it("renders results when the read succeeds", async () => {
    respond(
      OK_APPTS,
      jsonResponse(200, {
        encounters: [
          {
            encounter: { id: 1, type: "office_visit", provider: "Dr. Patel" },
            records: [{ id: 10, kind: "lab", test: "Hemoglobin A1c", value: 5.4, status: "normal" }],
          },
        ],
      })
    );
    render(<DashboardPage />);

    expect(await screen.findByText("Hemoglobin A1c")).toBeInTheDocument();
    expect(screen.queryByText(RESULTS_EMPTY)).toBeNull();
    expect(screen.queryByText(/could not be loaded/i)).toBeNull();
  });
});
