import { describe, expect, it } from 'vitest';

import { GET } from './+server';

// Harness smoke test for the `server` project. It satisfies no FE-R requirement
// — it exists so a broken Node-side harness fails here rather than in the first
// test that matters.
describe('harness smoke · server project', () => {
	it('answers the liveness probe the compose healthcheck polls', async () => {
		const response = await GET({} as never);

		expect(response.status).toBe(200);
		await expect(response.json()).resolves.toEqual({ status: 'ok', service: 'portal' });
	});
});
