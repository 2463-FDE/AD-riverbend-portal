import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

export async function POST(req: NextRequest) {
  const body = await req.json();
  return proxy(req, "/ai/visit-chat", { method: "POST", body });
}
