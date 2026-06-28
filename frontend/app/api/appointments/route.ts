import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

export async function GET(req: NextRequest) {
  const patientId = req.nextUrl.searchParams.get("patient_id") ?? "";
  return proxy(req, `/appointments?patient_id=${encodeURIComponent(patientId)}`);
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  // body: {patient_id, slot_id, provider, reason}
  return proxy(req, "/appointments", { method: "POST", body });
}
