import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { playwright } from '@vitest/browser-playwright';
import { defineConfig } from 'vitest/config';

// adapter-node, not adapter-auto: the portal's server layer holds the gateway
// session token (ADR 0014), so a Node server has to exist at runtime. It also
// gives ORIGIN as a runtime environment variable rather than a build constant
// (ADR 0015 §3).
//
// There is deliberately no `portal/svelte.config.js`. SvelteKit 2.x accepts the
// whole config inline through the `sveltekit()` Vite plugin, and that is the
// shape `sv create` scaffolds now; the separate file is the older surface, not a
// requirement. Review round 1 read the absence as a broken build; it is not.
// Proof, from a clean tree: `rm -rf build .svelte-kit && npm run build`
// prints "Using @sveltejs/adapter-node" and emits `build/index.js`, and
// `docker compose build --no-cache portal` does the same inside the image.
export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			adapter: adapter()
		})
	],

	// Two projects, split by what the test needs to be true (ADR 0013 §1).
	// The `.svelte.test.ts` suffix is load-bearing: it is what the Svelte compiler
	// treats as rune-capable AND what these globs discriminate on, so a misnamed
	// file silently runs in the wrong environment.
	test: {
		projects: [
			{
				extends: './vite.config.ts',
				test: {
					name: 'client',
					// Component behaviour is asserted in a real browser engine, never in a
					// DOM shim — the invariant the Chromium download is bought for.
					include: ['src/**/*.svelte.test.ts'],
					browser: {
						enabled: true,
						headless: true,
						provider: playwright(),
						instances: [{ browser: 'chromium' }],
						// Browser mode writes a PNG of the rendered component on every
						// failure. Component tests are fed fixtures rather than live data,
						// but patient-SHAPED fixtures are what the identity-banner and
						// intake tests will carry, and an image of one is the CI artifact
						// surface ADR 0013 §2 declined to acquire. Off, so it cannot be
						// acquired by accident; failures still report the DOM.
						screenshotFailures: false
					}
				}
			},
			{
				extends: './vite.config.ts',
				test: {
					name: 'server',
					environment: 'node',
					include: ['src/**/*.test.ts', 'tests/**/*.test.ts'],
					exclude: ['src/**/*.svelte.test.ts']
				}
			}
		]
	}
});
