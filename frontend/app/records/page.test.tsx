import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import RecordsPage from "./page";

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

const CHART = jsonResponse(200, {
  patient_id: 1042,
  encounters: [
    {
      encounter: {
        id: 1,
        type: "office_visit",
        provider: "Dr. Patel",
        summary: "Annual physical.",
        date: "2026-01-12T09:00:00Z",
      },
      records: [{ id: 10, kind: "note", body: "Unremarkable." }],
    },
  ],
});

function relevant(over: Record<string, unknown> = {}) {
  return jsonResponse(200, {
    patient_id: 1042,
    duplicate_disclosure: "none",
    items: [
      {
        record_id: 30,
        kind: "note",
        title: "Penicillin allergy noted",
        occurred_at: "2026-03-04T11:30:00Z",
        reason: "allergy",
      },
    ],
    ...over,
  });
}

// The chart fetch and the helper fetch are separate calls in a fixed order.
function respond(chart: Response, helper: Response) {
  apiFetch.mockResolvedValueOnce(chart).mockResolvedValueOnce(helper);
}

async function loadChart() {
  render(<RecordsPage />);
  fireEvent.click(screen.getByRole("button", { name: /load/i }));
}

beforeEach(() => {
  apiFetch.mockReset();
});

describe("records page relevant-records panel", () => {
  it("renders the ranked panel on chart open (W2-SPEC-1)", async () => {
    respond(CHART, relevant());
    await loadChart();

    expect(await screen.findByText("Penicillin allergy noted")).toBeInTheDocument();
    expect(screen.getByText("Allergy recorded")).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith("/api/patients/1042/relevant-records");
  });

  it("shows the duplicate disclosure without naming a sibling chart (W2-SPEC-3, 5)", async () => {
    respond(CHART, relevant({ duplicate_disclosure: "candidate" }));
    await loadChart();

    const banner = await screen.findByText(/may have more than one chart/i);
    expect(banner).toBeInTheDocument();
    expect(banner).toHaveClass("rb-alert--warn");
    expect(banner).toHaveTextContent(/may be incomplete/i);
    // No sibling id and no navigation out of this chart: the disclosure says
    // other charts MAY exist, never which.
    expect(screen.queryByText(/1330|1588/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows no disclosure when the chart is not a candidate duplicate", async () => {
    respond(CHART, relevant());
    await loadChart();
    await screen.findByText("Penicillin allergy noted");
    expect(screen.queryByText(/may have more than one chart/i)).not.toBeInTheDocument();
  });

  it("never blocks or delays the chart when the helper fails (W2-SPEC-2, 6)", async () => {
    // Only the helper call is rejected — stopping the whole backend would fail
    // the chart fetch too and prove nothing about the split.
    apiFetch
      .mockResolvedValueOnce(CHART)
      .mockRejectedValueOnce(new Error("connect ECONNREFUSED records-service:8073"));
    await loadChart();

    // The chart still renders...
    expect(await screen.findByText("Annual physical.")).toBeInTheDocument();
    expect(screen.getByText("Unremarkable.")).toBeInTheDocument();
    // ...and the fallback is explicit that duplicate status is UNCONFIRMED,
    // rather than silently reading as "no duplicates".
    const fallback = await screen.findByText(/duplicate-chart status is not confirmed/i);
    expect(fallback).toBeInTheDocument();
    expect(fallback).toHaveTextContent(/possibly incomplete/i);
    // No upstream error string reaches the DOM.
    expect(screen.queryByText(/ECONNREFUSED|records-service:8073/)).not.toBeInTheDocument();
  });

  it("treats a non-2xx helper response as unavailable, not as 'no duplicates'", async () => {
    respond(CHART, jsonResponse(503, { detail: "database unavailable" }));
    await loadChart();

    expect(
      await screen.findByText(/duplicate-chart status is not confirmed/i)
    ).toBeInTheDocument();
    expect(screen.queryByText(/database unavailable/)).not.toBeInTheDocument();
  });

  it("treats an off-contract helper body as unavailable", async () => {
    // gateway `_get` answers 200 with {"error": …} and the BFF proxy answers 200
    // for a body it could not parse, so a partial body is reachable. Rendering
    // one would drop the disclosure — the one field that must not be assumed.
    respond(CHART, jsonResponse(200, { patient_id: 1042, items: [] }));
    await loadChart();

    expect(
      await screen.findByText(/duplicate-chart status is not confirmed/i)
    ).toBeInTheDocument();
  });

  it("renders the chart normally when the helper returns no items", async () => {
    respond(CHART, relevant({ items: [] }));
    await loadChart();

    expect(await screen.findByText("Annual physical.")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText(/most relevant records/i)).not.toBeInTheDocument()
    );
    expect(screen.queryByText(/status is not confirmed/i)).not.toBeInTheDocument();
  });

  it("re-reads the panel when a different chart is opened", async () => {
    respond(CHART, relevant({ duplicate_disclosure: "candidate" }));
    render(<RecordsPage />);
    fireEvent.click(screen.getByRole("button", { name: /load/i }));
    await screen.findByText(/may have more than one chart/i);

    respond(CHART, relevant({ duplicate_disclosure: "none" }));
    fireEvent.change(screen.getByLabelText(/patient id/i), { target: { value: "1043" } });
    fireEvent.click(screen.getByRole("button", { name: /load/i }));

    await waitFor(() =>
      expect(screen.queryByText(/may have more than one chart/i)).not.toBeInTheDocument()
    );
    expect(apiFetch).toHaveBeenLastCalledWith("/api/patients/1043/relevant-records");
  });
});

describe("patient chart read surface (E5-SPEC-5 .. E5-SPEC-8)", () => {
  // The sixth unchecked read, found by the e5 drift gate and covered by spec
  // D-12. `json.encounters ?? []` rendered an outage as "No records found for
  // this patient." — on a PHI read surface, twenty lines above a sibling
  // function that already did this correctly.
  const CHART_EMPTY = "No records found for this patient.";
  const HELPER_OK = jsonResponse(200, {
    patient_id: 1042,
    duplicate_disclosure: "none",
    items: [],
  });

  it("renders a failed load, not an empty chart, on a gateway failure status", async () => {
    respond(jsonResponse(503, { detail: "records service unreachable" }), HELPER_OK);
    await loadChart();

    expect(await screen.findByText(/records could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(CHART_EMPTY)).toBeNull();
  });

  it("renders a failed load when a 200 body carries no encounters array", async () => {
    respond(jsonResponse(200, { detail: "records service error" }), HELPER_OK);
    await loadChart();

    expect(await screen.findByText(/records could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(CHART_EMPTY)).toBeNull();
  });

  it("still renders the empty state for a patient with genuinely no records", async () => {
    respond(jsonResponse(200, { patient_id: 1042, encounters: [] }), HELPER_OK);
    await loadChart();

    expect(await screen.findByText(CHART_EMPTY)).toBeInTheDocument();
    expect(screen.queryByText(/records could not be loaded/i)).toBeNull();
  });

  it("puts no exception text on the failed state", async () => {
    // The catch branch used to render e.message into the status line. Exception
    // text is not a user-facing sentence, and the failed state must be one
    // state rather than two spellings of it.
    apiFetch
      .mockRejectedValueOnce(new Error("connect ECONNREFUSED records-service:8073"))
      .mockResolvedValueOnce(HELPER_OK);
    await loadChart();

    expect(await screen.findByText(/records could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(/ECONNREFUSED|records-service:8073/)).toBeNull();
  });

  it("still fetches the relevant-records helper when the chart read fails", async () => {
    // W2-SPEC-2 runs both ways: the helper is fetched separately so neither
    // call gates the other. A failed chart must not silently drop the
    // duplicate-chart disclosure.
    respond(jsonResponse(503, { detail: "records service unreachable" }), HELPER_OK);
    await loadChart();

    await screen.findByText(/records could not be loaded/i);
    expect(apiFetch).toHaveBeenLastCalledWith("/api/patients/1042/relevant-records");
  });
});
