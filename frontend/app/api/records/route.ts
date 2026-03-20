import { NextRequest, NextResponse } from "next/server";

const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8070";

export async function GET(req: NextRequest) {
  const patientId = req.nextUrl.searchParams.get("patient_id") ?? "";
  try {
    // No ownership check — whatever id is passed is fetched.
    const res = await fetch(`${GATEWAY_URL}/patients/${patientId}/records`);
    const data = await res.json();
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "gateway unreachable" },
      { status: 502 }
    );
  }
}
