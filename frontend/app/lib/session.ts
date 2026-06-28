"use client";

import type { PortalUser } from "./types";

// Client-side session helpers. Per RIV teaching notes, the only "auth" the
// portal does is stash the token in localStorage — there is no refresh, no
// expiry handling, and no real route-guard enforcement on the backend.

const TOKEN_KEY = "riverbend.token";
const USER_KEY = "riverbend.user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getUser(): PortalUser | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as PortalUser;
  } catch {
    return null;
  }
}

export function setSession(token: string, user: PortalUser): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

// fetch wrapper that attaches the bearer token to our own /api routes. The
// route handlers forward it to the gateway.
export async function apiFetch(
  input: string,
  init: RequestInit = {}
): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(input, { ...init, headers });
}
