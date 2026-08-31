import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

// eligibility-assistant SPEC-25 (eligibility-assistant-D-16, D-41): the portal
// mints the turn's correlation id — a UUIDv4, one per turn, carrying no patient
// or member identity — and stamps when it sent the turn. Both ride as HEADERS,
// never body fields, so the gateway and assistant request shapes stay
// `extra="forbid"` (eligibility-assistant-D-46).
export async function POST(req: NextRequest) {
  const body = await req.json();
  return proxy(req, "/ai/visit-chat", {
    method: "POST",
    body,
    headers: {
      "X-Correlation-Id": crypto.randomUUID(),
      "X-Portal-Sent-At": new Date().toISOString(),
    },
  });
}
