import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";
import IntakePage from "./page";

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

// Fill the wizard up to (not including) the submit click. The three required
// fields, the two required consents and the submit button live on three
// different steps, so reaching Review is field entry plus three Continue
// clicks, not one form fill.
async function fillWizard() {
  // step 0 — Demographics
  fireEvent.change(screen.getByLabelText(/first name/i), { target: { value: "Ada" } });
  fireEvent.change(screen.getByLabelText(/last name/i), { target: { value: "Lovelace" } });

  // DOB is a popover DateField, not a text input: open it and pick today's
  // cell. `disableFuture` guarantees today is enabled, so no fixed date is
  // needed and the test does not drift with the clock.
  fireEvent.click(screen.getByLabelText(/date of birth/i));
  const dialog = await screen.findByRole("dialog");
  const today = within(dialog)
    .getAllByRole("gridcell")
    .map((cell) => cell.querySelector("button") ?? cell)
    .find((el) => el.closest("[data-today]") !== null || el.hasAttribute("data-today"));
  expect(today, "DayPicker rendered no today cell").toBeTruthy();
  fireEvent.click(today as Element);

  fireEvent.click(screen.getByRole("button", { name: /continue/i }));

  // step 1 — Insurance: deliberately left blank. Every field is optional and
  // Continue is ungated, and the empty state pins the fetchInstructions
  // payload shape (has_insurance=false, plan_type=null).
  fireEvent.click(screen.getByRole("button", { name: /continue/i }));

  // step 2 — Consents: the two required ones.
  fireEvent.click(screen.getByLabelText(/consent to treatment/i));
  // (HIPAA) disambiguates from the optional ROI consent, whose body also cites
  // the Notice of Privacy Practices.
  fireEvent.click(screen.getByLabelText(/notice of privacy practices \(hipaa\)/i));
  fireEvent.click(screen.getByRole("button", { name: /continue/i }));
}

// Fill, then submit against a given response, and wait for the page to settle.
async function submitWith(status: number, body: unknown) {
  await fillWizard();
  apiFetch.mockResolvedValueOnce(jsonResponse(status, body));
  fireEvent.click(screen.getByRole("button", { name: /submit intake/i }));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: /submit intake/i })?.hasAttribute("disabled")).not
      .toBe(true),
  );
}

// The visit-prep checklist is gated behind a CONFIRMED registration, so the
// mocked 200 has to carry a patient_id — a success status that confirms no
// record is no longer a success (E4-SPEC-5).
async function submitIntake() {
  await submitWith(201, { patient_id: 5001, elapsed_seconds: 0.4 });
  await screen.findByRole("button", { name: /get visit prep instructions/i });
}

beforeEach(() => {
  apiFetch.mockReset();
});

describe("intake visit-prep checklist surface", () => {
  it("renders instructions produced through the LLM client path (W1-SPEC-19)", async () => {
    render(<IntakePage />);
    await submitIntake();

    apiFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        items: ["Bring a photo ID", "Arrive 15 minutes early"],
        disclaimer: "This is general guidance, not medical advice.",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: /get visit prep instructions/i }));

    expect(await screen.findByText("Bring a photo ID")).toBeTruthy();
    expect(screen.getByText("Arrive 15 minutes early")).toBeTruthy();
    expect(screen.getByText("This is general guidance, not medical advice.")).toBeTruthy();

    const call = apiFetch.mock.calls[apiFetch.mock.calls.length - 1];
    expect(call[0]).toBe("/api/ai/intake-instructions");
  });

  it("shows a deterministic fallback when the provider fails, never the downstream detail (W1-SPEC-20)", async () => {
    render(<IntakePage />);
    await submitIntake();

    apiFetch.mockResolvedValueOnce(
      jsonResponse(502, { detail: "assistant is temporarily unavailable" }),
    );
    fireEvent.click(screen.getByRole("button", { name: /get visit prep instructions/i }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Could not prepare your checklist right now.");
    // The negative half: the fallback is deterministic, not a relayed error.
    // The downstream `detail` must never reach the DOM.
    await waitFor(() => {
      expect(document.body.textContent).not.toContain("assistant is temporarily unavailable");
    });
  });

  it("shows a deterministic fallback when the call cannot be made at all (W1-SPEC-20)", async () => {
    render(<IntakePage />);
    await submitIntake();

    apiFetch.mockRejectedValueOnce(new Error("NetworkError at https://portal.internal/api"));
    fireEvent.click(screen.getByRole("button", { name: /get visit prep instructions/i }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Could not reach the portal.");
    expect(document.body.textContent).not.toContain("NetworkError");
    expect(document.body.textContent).not.toContain("portal.internal");
  });
});

describe("registration outcome (E4)", () => {
  it("confirms a registration only when the response carries a patient id (E4-SPEC-5)", async () => {
    render(<IntakePage />);
    await submitWith(201, { patient_id: 5001, elapsed_seconds: 0.4 });

    const status = await screen.findByRole("status");
    expect(status.textContent).toContain("5001");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("treats a success status that confirms no record as a failure (E4-SPEC-5)", async () => {
    // The defect's own shape one layer up: the gateway used to answer 200 for a
    // registration that created nothing, and the page printed a fallback
    // success string. A 2xx with no patient_id is a system failure now.
    render(<IntakePage />);
    await submitWith(200, { message: "Intake received" });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("was not saved");
    expect(alert.textContent).toContain("system could not complete it");
    expect(document.body.textContent).not.toContain("Intake submitted");
  });

  it("tells the operator a rejected submission is correctable at the desk (E4-SPEC-6)", async () => {
    render(<IntakePage />);
    await submitWith(422, { detail: "demographics.name: Field required" });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("was not saved");
    expect(alert.textContent).toContain("correct them at the desk");
    // The downstream detail is never relayed: it can carry the submitted
    // values that were rejected.
    expect(document.body.textContent).not.toContain("Field required");
  });

  it("tells the operator a failed submission is a system failure, not a form problem (E4-SPEC-7)", async () => {
    render(<IntakePage />);
    await submitWith(502, { detail: "intake service unreachable" });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("system could not complete it");
    expect(alert.textContent).not.toContain("correct them at the desk");
    expect(document.body.textContent).not.toContain("intake service unreachable");
  });

  it("keeps a 400 on the correctable side of the split (E4-SPEC-6, E4-SPEC-14)", async () => {
    render(<IntakePage />);
    await submitWith(400, { detail: "bad request" });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("correct them at the desk");
  });

  it("renders the payer verdict on the confirmation (E4-SPEC-24)", async () => {
    render(<IntakePage />);
    await submitWith(201, {
      patient_id: 5001,
      eligibility: { active: true, status: "active" },
    });

    expect(await screen.findByText("Coverage active")).toBeTruthy();
  });

  it("renders a degraded verdict as not-a-denial, never as absent (E4-SPEC-24)", async () => {
    render(<IntakePage />);
    await submitWith(201, {
      patient_id: 5001,
      eligibility: { active: null, status: "unknown", reason: "eligibility check failed" },
    });

    expect(await screen.findByText("Unverified — not a denial")).toBeTruthy();
  });

  it("says so explicitly when there is no verdict at all (E4-SPEC-25)", async () => {
    render(<IntakePage />);
    await submitWith(201, { patient_id: 5001, eligibility: null });

    expect(await screen.findByText(/eligibility was not checked/i)).toBeTruthy();
  });

  it("shows the not-checked line for a verdict outside the vocabulary (E4-SPEC-25)", async () => {
    // The accepted residual, pinned rather than left to drift: VerdictBadge
    // renders only active|inactive|unknown|pending, so anything else falls into
    // the not-checked line rather than rendering nothing at all.
    render(<IntakePage />);
    await submitWith(201, {
      patient_id: 5001,
      eligibility: { active: null, status: "degraded_but_answering" },
    });

    expect(await screen.findByText(/eligibility was not checked/i)).toBeTruthy();
  });

  it("sends the service's payload shape, not the form's (E4-SPEC-1, E4-SPEC-3)", async () => {
    render(<IntakePage />);
    await submitWith(201, { patient_id: 5001 });

    const call = apiFetch.mock.calls[0];
    expect(call[0]).toBe("/api/intake");
    const body = JSON.parse((call[1] as { body: string }).body);
    expect(body.demographics.name).toBe("Ada Lovelace");
    expect(body.demographics.first_name).toBeUndefined();
    expect(body.consents).toEqual(["treatment_consent", "npp_ack"]);
    expect(body.insurance).toBeNull();
    expect(JSON.stringify(body)).not.toContain("policy_holder");
  });
});

describe("intake submission identifier (E5-SPEC-26, E5-SPEC-35, E5-SPEC-38)", () => {
  it("carries the same identifier across every re-submission of one attempt", async () => {
    // The whole point of the identifier: the first attempt may have committed a
    // registration whose response was lost, so the retry has to be recognisable
    // as the SAME attempt. A fresh value per submission would create the second
    // chart this closes.
    render(<IntakePage />);
    await submitWith(503, { detail: "registration store unavailable" });

    apiFetch.mockResolvedValueOnce(jsonResponse(201, { patient_id: 5001 }));
    fireEvent.click(screen.getByRole("button", { name: /submit intake/i }));
    await waitFor(() => expect(apiFetch.mock.calls.length).toBe(2));

    const ids = apiFetch.mock.calls.map(
      (call) => JSON.parse((call[1] as { body: string }).body).submission_id,
    );
    expect(ids[0]).toBeTruthy();
    expect(ids[1]).toBe(ids[0]);
  });

  it("mints a fresh identifier for a genuinely new registration", async () => {
    // E5-SPEC-35. A new registration reaches the form by a fresh mount, and it
    // must not replay the previous patient's confirmation.
    render(<IntakePage />);
    await submitWith(201, { patient_id: 5001 });
    const first = JSON.parse((apiFetch.mock.calls[0][1] as { body: string }).body).submission_id;

    cleanup();
    apiFetch.mockReset();
    render(<IntakePage />);
    await submitWith(201, { patient_id: 5002 });
    const second = JSON.parse((apiFetch.mock.calls[0][1] as { body: string }).body).submission_id;

    expect(second).not.toBe(first);
  });

  // E5-SPEC-43, plan D-20. The pair to "same attempt": an edited form is a
  // DIFFERENT attempt. Without this the operator who lost a response, corrected
  // a typo and resubmitted would keep sending the original attempt's identifier
  // — answered, before the service-side fix, with a confirmation of the chart
  // that never got the correction (codex PR #76 round 2), and after it with a
  // 409 the form would resubmit forever. The re-mint is the operator-facing
  // resolution; the 409 is defence in depth for non-portal callers.
  const submittedIds = () =>
    apiFetch.mock.calls.map(
      (call) => JSON.parse((call[1] as { body: string }).body).submission_id,
    );

  // The review step has no fields, so an edit is what the operator actually
  // does: Back to the consents step, toggle one, Continue.
  function editOneField(label: RegExp) {
    fireEvent.click(screen.getByRole("button", { name: /^back$/i }));
    fireEvent.click(screen.getByLabelText(label));
    fireEvent.click(screen.getByRole("button", { name: /continue/i }));
  }

  async function resubmit(response: () => void) {
    response();
    fireEvent.click(screen.getByRole("button", { name: /submit intake/i }));
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /submit intake/i })?.hasAttribute("disabled"))
        .not.toBe(true),
    );
  }

  it("treats an edit after a failed submit as a new attempt (E5-SPEC-43)", async () => {
    render(<IntakePage />);
    await submitWith(503, { detail: "registration store unavailable" });

    editOneField(/release of information/i);
    await resubmit(() => apiFetch.mockResolvedValueOnce(jsonResponse(201, { patient_id: 5001 })));

    const ids = submittedIds();
    expect(ids).toHaveLength(2);
    expect(ids[1]).not.toBe(ids[0]);
  });

  it("mints once for several edits between two submits (E5-SPEC-43)", async () => {
    // The flag is cleared by the first edit, so the second does not mint again:
    // one unconfirmed submit plus any number of corrections is ONE new attempt,
    // and the retry of that attempt still has to be replayable.
    render(<IntakePage />);
    await submitWith(503, { detail: "registration store unavailable" });

    editOneField(/release of information/i);
    editOneField(/financial responsibility/i);
    await resubmit(() =>
      apiFetch.mockResolvedValueOnce(jsonResponse(503, { detail: "registration store unavailable" })),
    );
    await resubmit(() => apiFetch.mockResolvedValueOnce(jsonResponse(201, { patient_id: 5001 })));

    const ids = submittedIds();
    expect(ids).toHaveLength(3);
    expect(ids[1]).not.toBe(ids[0]);
    // Two edits, one new identifier; and the unedited retry of the second
    // attempt still carries it, or a lost response could not be replayed.
    expect(ids[2]).toBe(ids[1]);
  });

  it("counts a submit that never reached the portal as unconfirmed (E5-SPEC-43)", async () => {
    // The network-error catch is exactly the lost window E5-SPEC-24 names: the
    // request may have registered. An edit after it must still be a new attempt.
    render(<IntakePage />);
    await fillWizard();
    apiFetch.mockRejectedValueOnce(new Error("network down"));
    fireEvent.click(screen.getByRole("button", { name: /submit intake/i }));
    await screen.findByText(/could not reach the portal/i);

    editOneField(/release of information/i);
    await resubmit(() => apiFetch.mockResolvedValueOnce(jsonResponse(201, { patient_id: 5001 })));

    const ids = submittedIds();
    expect(ids[1]).not.toBe(ids[0]);
  });

  it("keeps the identifier when a rejected submission is retried unchanged", async () => {
    // A correctable rejection recorded nothing, so the unedited retry creates
    // the registration rather than replaying — and reusing the identifier keeps
    // the guarantee if the rejection was in fact a lost success.
    render(<IntakePage />);
    await submitWith(422, { detail: "submission_id must be a version 4 UUID" });

    await resubmit(() => apiFetch.mockResolvedValueOnce(jsonResponse(201, { patient_id: 5001 })));

    const ids = submittedIds();
    expect(ids[1]).toBe(ids[0]);
  });

  it("derives the identifier from nothing the operator typed (E5-SPEC-38)", async () => {
    // A key hashed from name/DOB/SSN would put PHI in a log line, a response
    // body and a stored column at once — and would collide for two genuine
    // registrations of one person, i.e. an accidental master patient index.
    render(<IntakePage />);
    await submitWith(201, { patient_id: 5001 });

    const body = JSON.parse((apiFetch.mock.calls[0][1] as { body: string }).body);
    const id: string = body.submission_id;
    expect(id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    for (const submitted of ["Ada", "Lovelace", "Ada Lovelace", body.demographics.dob]) {
      expect(id).not.toContain(String(submitted));
    }
  });
});
