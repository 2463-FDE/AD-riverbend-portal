import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const providerId = sp.get("provider_id") ?? "";
  const limit = sp.get("limit") ?? "20";
  const qs = new URLSearchParams({ limit });
  if (providerId) qs.set("provider_id", providerId);
  return proxy(req, `/slots?${qs.toString()}`);
}
