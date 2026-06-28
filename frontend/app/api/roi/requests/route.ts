import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

export async function GET(req: NextRequest) {
  const patientId = req.nextUrl.searchParams.get("patient_id") ?? "";
  return proxy(req, `/roi/requests?patient_id=${encodeURIComponent(patientId)}`);
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  // body: {patient_id, recipient, recipient_type, purpose,
  //        date_range_start, date_range_end}
  return proxy(req, "/roi/requests", { method: "POST", body });
}
