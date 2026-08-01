import { describe, expect, it } from 'vitest';

/**
 * ADR 0013 §4 invariant: at least one CI execution of the whole JS suite runs
 * under an ambient `TZ` that is **not** the clinic's, so an accidental
 * ambient-zone dependency in the `FE-R8` formatter fails instead of passing by
 * luck on a machine that happens to sit in Eastern time.
 *
 * The mechanism is `TZ=America/Chicago` on the `test` script. This test is what
 * stops that prefix being dropped as noise: without it the invariant is a shell
 * string nothing checks. Chicago is the ADR's value because it is the zone the
 * machine was in when slots rendered 03:00–06:00.
 */
describe('ADR 0013 §4 · the JS suite runs under a non-clinic ambient timezone', () => {
	const CLINIC_ZONE = 'America/New_York';

	it('does not run under the clinic timezone', () => {
		expect(Intl.DateTimeFormat().resolvedOptions().timeZone).not.toBe(CLINIC_ZONE);
	});

	it('runs under the zone the harness pins', () => {
		expect(Intl.DateTimeFormat().resolvedOptions().timeZone).toBe('America/Chicago');
	});
});
