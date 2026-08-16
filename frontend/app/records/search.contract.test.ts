import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { isRecordSearch, RECORD_SEARCH_FIELDS, RECORD_SEARCH_HIT_FIELDS } from "./search";

// Portal side of the GET /records/search response declaration (e6-SPEC-5,
// e6-D-16). The service side is tests/test_records_search_bounds.py; both assert
// against this one file, and both jobs gate docker-build, so either half
// drifting reddens its own job. Read with node:fs (not an import) for the same
// reason the intake contract test does — an import would pull a path outside
// frontend/ into the type-checked project.
function contractPath(): string {
  let dir = process.cwd();
  for (let i = 0; i < 5; i += 1) {
    const candidate = resolve(dir, "contracts/records-search.json");
    if (existsSync(candidate)) return candidate;
    dir = resolve(dir, "..");
  }
  throw new Error(`contracts/records-search.json not found above ${process.cwd()}`);
}

const CONTRACT = JSON.parse(readFileSync(contractPath(), "utf8")) as {
  response_fields: Record<string, string[]>;
  sample_response: { hits: unknown[]; truncated: boolean };
};

describe("GET /records/search response contract (portal side)", () => {
  it("reads exactly the declared root fields", () => {
    expect([...RECORD_SEARCH_FIELDS].sort()).toEqual([...CONTRACT.response_fields.root].sort());
  });

  it("reads exactly the declared hit fields", () => {
    expect([...RECORD_SEARCH_HIT_FIELDS].sort()).toEqual([...CONTRACT.response_fields.hit].sort());
  });

  it("accepts the declared sample response through the portal guard", () => {
    expect(isRecordSearch(CONTRACT.sample_response)).toBe(true);
  });

  it("rejects a response missing the truncated (withheld) signal", () => {
    // The whole point of the wrapper is the withheld signal; a body without it
    // must be treated as off-contract, not as an exhausted result set.
    const { truncated: _drop, ...noFlag } = CONTRACT.sample_response;
    expect(isRecordSearch(noFlag)).toBe(false);
  });
});
