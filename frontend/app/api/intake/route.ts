import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

export async function POST(req: NextRequest) {
  const body = await req.json();

  // RIV-088 (fixed, ADR 0010): this route used to sleep 4200ms to mirror the
  // backend's synthetic eligibility delay, which was the user-visible "spin" the
  // front desk complained about. The backend eligibility call is now bounded and
  // that seeded delay is gone, so the portal proxies straight through.
  return proxy(req, "/intake", { method: "POST", body });
}
