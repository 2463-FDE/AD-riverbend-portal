import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import globals from 'globals';
import ts from 'typescript-eslint';

// eslint covers what the compiler does not: unused bindings, import hygiene,
// `no-at-html-tags`. It deliberately does NOT widen the FE-R17 accessible-name
// gate — eslint-plugin-svelte@3.22.0 ships 85 rules and zero a11y rules, so
// `svelte-check --fail-on-warnings` remains the whole of that gate (spec §8 #15,
// corrected by measurement; ADR 0013 gap #9 owns the uncovered surface).
export default ts.config(
	{
		ignores: ['.svelte-kit/', 'build/', 'node_modules/']
	},
	js.configs.recommended,
	ts.configs.recommended,
	svelte.configs.recommended,
	{
		languageOptions: {
			globals: { ...globals.browser, ...globals.node }
		}
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts'],
		languageOptions: {
			parserOptions: {
				parser: ts.parser,
				extraFileExtensions: ['.svelte']
			}
		}
	}
);
