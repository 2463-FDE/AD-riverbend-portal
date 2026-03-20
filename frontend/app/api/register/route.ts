import { NextRequest, NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8070";

export async function POST(req: NextRequest) {
  const body = await req.json();

  // Registration is slow (~4-5s) — RIV-088. The intake-service makes a
  // synchronous, no-timeout eligibility call on the request path before it
  // confirms, so the whole Save blocks behind it. Mirrored here so the
  // portal behaves the same way when the backend isn't up.
  await new Promise((r) => setTimeout(r, 4200));

  try {
    const res = await fetch(`${GATEWAY_URL}/intake`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "gateway unreachable" },
      { status: 502 }
    );
  }
}
