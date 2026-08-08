import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import VerdictBadge, { verdictTone } from "./VerdictBadge";

// Explicit: RTL registers its auto-cleanup only when Vitest runs with globals,
// and this project deliberately does not (e1 — tests import their own
// describe/it/expect). Without this, renders accumulate across cases and a
// role query matches the previous test's badge.
afterEach(cleanup);

// W3-SPEC-17 / W3-SPEC-18. This component exists ONLY because the shared
// StatusBadge tone map inverts the rule these tests pin: it renders
// unknown/unverified as `neutral` (quieter than a denial) while `denied` is
// `bad`. The invariants below are the reason for the duplication — if they ever
// hold for StatusBadge too, delete this component, not these tests.
describe("VerdictBadge", () => {
  it("renders an active verdict as an ok badge (W3-SPEC-17)", () => {
    render(<VerdictBadge eligibility={{ status: "active" }} />);
    const badge = screen.getByRole("status");
    expect(badge).toHaveTextContent("Coverage active");
    expect(badge).toHaveClass("rb-badge", "rb-badge--ok");
  });

  it("marks an unknown verdict explicitly unverified, not a denial (W3-SPEC-17)", () => {
    render(<VerdictBadge eligibility={{ status: "unknown" }} />);
    const badge = screen.getByRole("status");
    expect(badge).toHaveTextContent("Unverified — not a denial");
    expect(badge).toHaveClass("rb-badge--warn");
  });

  it("marks a pending verdict explicitly pending, not a denial (W3-SPEC-17)", () => {
    render(<VerdictBadge eligibility={{ status: "pending" }} />);
    const badge = screen.getByRole("status");
    expect(badge).toHaveTextContent("Pending verification — not a denial");
    expect(badge).toHaveClass("rb-badge--warn");
  });

  it("renders a payer-confirmed inactive verdict as the denial tone (W3-SPEC-18)", () => {
    render(<VerdictBadge eligibility={{ status: "inactive" }} />);
    const badge = screen.getByRole("status");
    expect(badge).toHaveTextContent("No active coverage (payer-confirmed)");
    expect(badge).toHaveClass("rb-badge--bad");
  });

  // NEGATIVE (docs/landmines.md §3): the whole point of the component. An
  // unverified outcome must never reach the denial tone, and must never be
  // rendered quieter than one either.
  it("never maps an unverified outcome to the denial or neutral tone (W3-SPEC-18)", () => {
    for (const status of ["unknown", "pending"]) {
      const tone = verdictTone(status);
      expect(tone).not.toBeNull();
      expect(tone!.variant).not.toBe("bad");
      expect(tone!.variant).not.toBe("neutral");
      expect(tone!.variant).toBe("warn");
    }
  });

  it("gives the denial tone to inactive alone (W3-SPEC-18)", () => {
    const bad = ["active", "unknown", "pending", "denied", "expired", ""].filter(
      (s) => verdictTone(s)?.variant === "bad"
    );
    expect(bad).toEqual([]);
    expect(verdictTone("inactive")?.variant).toBe("bad");
  });

  it("renders nothing for an absent or unrecognised verdict (W3-SPEC-18)", () => {
    const { container: none } = render(<VerdictBadge eligibility={null} />);
    expect(none).toBeEmptyDOMElement();

    const { container: noStatus } = render(<VerdictBadge eligibility={{}} />);
    expect(noStatus).toBeEmptyDOMElement();

    // An unrecognised status is a vocabulary the portal has not been taught.
    // Guessing a tone is how "denied" would be invented client-side.
    const { container: unknownWord } = render(
      <VerdictBadge eligibility={{ status: "wibble" }} />
    );
    expect(unknownWord).toBeEmptyDOMElement();
    expect(verdictTone("wibble")).toBeNull();
    expect(verdictTone(null)).toBeNull();
  });
});
