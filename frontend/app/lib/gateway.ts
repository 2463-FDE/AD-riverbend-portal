import { NextRequest, NextResponse } from "next/server";

// Server-side base URL for the API gateway. Route handlers run on the server,
// so this is the only place GATEWAY_URL is read for proxying.
export const GATEWAY_URL = process.env.GATEWAY_URL || "http://localhost:8070";

// Build headers for an upstream gateway call, forwarding the caller's bearer
// token. The browser keeps the token in localStorage and attaches it as an
// Authorization header to our /api routes; we pass it straight through.
export function gatewayHeaders(req: NextRequest, json = true): HeadersInit {
  const headers: Record<string, string> = {};
  const auth = req.headers.get("authorization");
  if (auth) headers["Authorization"] = auth;
  if (json) headers["Content-Type"] = "application/json";
  return headers;
}

interface ProxyOptions {
  method?: string;
  body?: unknown;
  // When false, do not forward/require Content-Type (e.g. GET).
  json?: boolean;
}

// Generic proxy helper: forwards a request to the gateway and relays the
// response. Network failures surface as a 502 with a JSON error body.
export async function proxy(
  req: NextRequest,
  path: string,
  opts: ProxyOptions = {}
): Promise<NextResponse> {
  const method = opts.method ?? "GET";
  const sendJson = opts.json ?? method !== "GET";
  try {
    const res = await fetch(`${GATEWAY_URL}${path}`, {
      method,
      headers: gatewayHeaders(req, sendJson),
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      cache: "no-store",
    });
    const text = await res.text();
    const data = text ? safeParse(text) : null;
    return NextResponse.json(data, { status: res.status });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "gateway unreachable" },
      { status: 502 }
    );
  }
}

function safeParse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}
