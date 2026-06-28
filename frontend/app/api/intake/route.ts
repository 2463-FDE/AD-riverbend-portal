import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

export async function POST(req: NextRequest) {
  const body = await req.json();

  // Registration/intake is slow (~4-5s) — RIV-088. The intake-service makes a
  // synchronous, no-timeout eligibility call on the request path before it
  // confirms, so the whole Submit blocks behind it. Mirrored here so the
  // portal "spins" the same way when the backend isn't up.
  await new Promise((r) => setTimeout(r, 4200));

  return proxy(req, "/intake", { method: "POST", body });
}
