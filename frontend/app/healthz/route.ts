import { NextResponse } from "next/server";

// E1-SPEC-10..12: truthful frontend health probe. Status-only, no auth, no
// upstream/gateway dependency, no PHI or secret in the body. If Next is serving
// pages it serves this route (200); if it is not serving, the request gets no
// success response (SPEC-11 satisfied by non-response). See docs/workflow/e1/.
export const dynamic = "force-dynamic"; // never statically cached

export function GET() {
  return NextResponse.json({ status: "ok" }, { status: 200 });
}
