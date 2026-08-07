import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import StatusBadge, { statusVariant } from "./StatusBadge";

// E1-SPEC-18: renders a real portal component and asserts on its rendered
// output (not a trivial always-pass). E1-SPEC-19: StatusBadge is pure
// presentational — no registration/TODO-1 or any deliberately defective flow.
describe("StatusBadge", () => {
  it("renders a confirmed status as an ok badge (E1-SPEC-18)", () => {
    render(<StatusBadge status="confirmed" />);
    const badge = screen.getByRole("status");
    expect(badge).toHaveTextContent("confirmed");
    expect(badge).toHaveAttribute("aria-label", "Status: confirmed");
    expect(badge).toHaveClass("rb-badge", "rb-badge--ok");
  });

  it("maps status strings to variants (E1-SPEC-18)", () => {
    expect(statusVariant("pending")).toBe("warn");
    expect(statusVariant("cancelled")).toBe("bad");
    expect(statusVariant("wibble")).toBe("neutral");
    expect(statusVariant(undefined)).toBe("neutral");
  });
});
