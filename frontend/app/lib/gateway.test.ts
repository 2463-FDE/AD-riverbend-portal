// eligibility-assistant SPEC-25 — the portal mints the turn's trace identity.
// The correlation id is a fresh UUIDv4 per turn (never reused, never derived
// from anything about the patient), sent as a HEADER beside the forwarded
// Authorization, with the send stamp riding the same hop.
import { afterEach, describe, expect, it, vi } from "vitest";
import type { NextRequest } from "next/server";

import { POST } from "../api/ai/visit-chat/route";

const UUID4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function portalRequest(): NextRequest {
  return new Request("http://portal.test/api/ai/visit-chat", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: "Bearer test-token",
    },
    body: JSON.stringify({
      message: "please check AETN1224",
      question_type: "covered_today",
      payer: "aetna",
      product: "commercial",
      state: "unconfirmed",
      emergency: false,
    }),
  }) as unknown as NextRequest;
}

describe("visit-chat route trace identity", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("correlation id minted per turn", async () => {
    const seen: Array<Record<string, string>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        seen.push({ ...(init.headers as Record<string, string>) });
        return new Response(JSON.stringify({ ok: true }), { status: 200 });
      })
    );

    await POST(portalRequest());
    await POST(portalRequest());

    expect(seen).toHaveLength(2);
    const [first, second] = seen;
    // A UUIDv4, minted here — not forwarded from the browser, not derived.
    expect(first["X-Correlation-Id"]).toMatch(UUID4);
    expect(second["X-Correlation-Id"]).toMatch(UUID4);
    // Fresh per turn: two turns never share a trace identity.
    expect(first["X-Correlation-Id"]).not.toBe(second["X-Correlation-Id"]);
    // The send stamp rides the same hop, and the caller's bearer still does.
    expect(Date.parse(first["X-Portal-Sent-At"])).not.toBeNaN();
    expect(first["Authorization"]).toBe("Bearer test-token");
  });
});
