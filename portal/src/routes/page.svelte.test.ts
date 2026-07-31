import { describe, expect, it } from 'vitest';
import { page } from 'vitest/browser';
import { render } from 'vitest-browser-svelte';

import Page from './+page.svelte';

// Harness smoke test for the `client` project. It satisfies no FE-R requirement
// — it exists so a broken browser harness fails here rather than in the first
// component test that matters, and so the `.svelte.test.ts` suffix is exercised
// (a misnamed file silently runs in the Node project instead).
describe('harness smoke · client project', () => {
	it('renders a component in a real browser engine', async () => {
		render(Page);

		await expect
			.element(page.getByRole('heading', { level: 1 }))
			.toHaveTextContent('Riverbend staff portal');
	});
});
