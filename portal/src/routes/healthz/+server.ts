import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

/**
 * Liveness surface for the compose healthcheck, matching the shape the ten
 * FastAPI services already expose.
 *
 * Scope note, so this is not read as more than it is: today it reports only
 * that the Node server is answering. ADR 0014's Consequences require it to
 * return non-200 when the cookie encryption key is absent or unusable, and
 * ADR 0015 §3 requires the same for a missing ORIGIN — both land with the
 * session module, which does not exist yet. It must never report the key
 * itself, a partial value, or a stack trace.
 */
export const GET: RequestHandler = () => json({ status: 'ok', service: 'portal' });
