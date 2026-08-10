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

// The visit-prep checklist is gated behind a submitted intake (page.tsx's
// `result?.ok` branch), and the three required fields, the two required
// consents and the submit button live on three different wizard steps — so
// reaching it is field entry plus three Continue clicks, not one form fill.
async function submitIntake() {
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
  fireEvent.click(screen.getByLabelText(/notice of privacy practices/i));
  fireEvent.click(screen.getByRole("button", { name: /continue/i }));

  // step 3 — Review & Submit. apiFetch is mocked, so the 200 here is NOT an
  // assertion that registration works: it neither exercises nor masks the
  // intake contract break (docs/debt-log.md, TODO-1), which is backend-side.
  apiFetch.mockResolvedValueOnce(jsonResponse(200, { message: "Intake received" }));
  fireEvent.click(screen.getByRole("button", { name: /submit intake/i }));
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
