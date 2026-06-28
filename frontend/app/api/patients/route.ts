import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  const q = sp.get("q") ?? "";
  const limit = sp.get("limit") ?? "20";
  const offset = sp.get("offset") ?? "0";
  const qs = new URLSearchParams({ q, limit, offset }).toString();
  return proxy(req, `/patients?${qs}`);
}
