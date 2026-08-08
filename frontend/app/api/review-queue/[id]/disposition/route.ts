import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await req.json();
  // `decided_by` is stamped from the session at the gateway; anything the
  // client sends under that key is overwritten there, not here.
  return proxy(req, `/review-queue/${encodeURIComponent(id)}/disposition`, {
    method: "POST",
    body,
  });
}
