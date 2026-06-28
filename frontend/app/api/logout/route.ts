import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

export async function POST(req: NextRequest) {
  return proxy(req, "/logout", { method: "POST", body: {} });
}
