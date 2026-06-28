import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

// Public — no Authorization required. Returns {token, user}.
export async function POST(req: NextRequest) {
  const body = await req.json();
  return proxy(req, "/login", { method: "POST", body });
}
