import { describe, it, expect } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { buildIntakePayload, newSubmissionId, CONSENT_KIND } from "./payload";
import type { ConsentsForm, DemographicsForm, InsuranceForm } from "./payload";

// Portal side of the shared POST /intake declaration (E4-SPEC-19, E4-SPEC-20). The
// service side is tests/test_intake_payload_contract.py; both assert against
// this one file, and both jobs gate docker-build, so either half drifting
// reddens its own job.
//
// Read with node:fs rather than an `import`, deliberately: an import would pull
// a path outside frontend/ into the TypeScript project that `next build`
// type-checks. Resolved by walking up from the working directory rather than
// from import.meta.url, which Vite rewrites to a non-file URL.
function contractPath(): string {
  let dir = process.cwd();
  for (let i = 0; i < 5; i += 1) {
    const candidate = resolve(dir, "contracts/intake-registration.json");
    if (existsSync(candidate)) return candidate;
    dir = resolve(dir, "..");
  }
  throw new Error(`contracts/intake-registration.json not found above ${process.cwd()}`);
}

const CONTRACT = JSON.parse(readFileSync(contractPath(), "utf8")) as {
  consent_kinds: string[];
  request_fields: Record<string, string[]>;
  portal_omits: Record<string, string[]>;
};

const DEMO: DemographicsForm = {
  first_name: "Sample",
  last_name: "Patient",
  dob: "1985-03-12",
  gender: "Prefer not to say",
  ssn: "000-00-0000",
  phone: "555-0100",
  email: "sample@example.invalid",
  address: "1 Example Way",
};

const INS: InsuranceForm = {
  carrier: "Example Health",
  member_id: "EXMP000001",
  group_number: "GRP-0001",
  plan_type: "PPO",
  policy_holder_is_self: true,
};

const CONSENTS: ConsentsForm = {
  treatment: true,
  privacy: true,
  financial: true,
  communications: true,
  roi: true,
};

const BLANK_INS: InsuranceForm = {
  carrier: "",
  member_id: "",
  group_number: "",
  plan_type: "",
  policy_holder_is_self: true,
};

const SID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301";

function expected(object: string): string[] {
  const omitted = new Set(CONTRACT.portal_omits[object] ?? []);
  return CONTRACT.request_fields[object].filter((f) => !omitted.has(f)).sort();
}

describe("POST /intake payload contract (portal side)", () => {
  it("sends exactly the declared root keys", () => {
    const payload = buildIntakePayload(DEMO, INS, CONSENTS, SID);
    expect(Object.keys(payload).sort()).toEqual(expected("root"));
  });

  it("sends exactly the declared demographics keys, minus the declared omissions", () => {
    const payload = buildIntakePayload(DEMO, INS, CONSENTS, SID);
    expect(Object.keys(payload.demographics).sort()).toEqual(expected("demographics"));
  });

  it("sends exactly the declared insurance keys", () => {
    const payload = buildIntakePayload(DEMO, INS, CONSENTS, SID);
    expect(Object.keys(payload.insurance ?? {}).sort()).toEqual(expected("insurance"));
  });

  it("maps the form's consent catalog onto the declared vocabulary, exactly", () => {
    // E4-SPEC-9, portal side: same set, nothing extra, nothing missing. The
    // pytest side asserts the same list against ConsentKind, so the two
    // vocabularies cannot drift apart without one of the two jobs going red.
    expect(Object.values(CONSENT_KIND).slice().sort()).toEqual(
      CONTRACT.consent_kinds.slice().sort(),
    );
  });

  it("sends the accepted consents as a list of kinds, not a boolean object", () => {
    const payload = buildIntakePayload(
      DEMO,
      INS,
      { ...CONSENTS, financial: false, roi: false },
      SID,
    );
    expect(payload.consents).toEqual(["treatment_consent", "npp_ack", "communications_opt_in"]);
  });

  it("sends one combined name, not first_name/last_name", () => {
    const payload = buildIntakePayload(DEMO, INS, CONSENTS, SID);
    expect(payload.demographics.name).toBe("Sample Patient");
    expect(JSON.stringify(payload)).not.toContain("first_name");
  });

  it("sends insurance: null when every insurance field is blank, keeping the root key", () => {
    const payload = buildIntakePayload(DEMO, BLANK_INS, CONSENTS, SID);
    expect(payload.insurance).toBeNull();
    expect("insurance" in payload).toBe(true);
  });

  it("sends nothing policy-holder-shaped (E4-SPEC-3)", () => {
    const blob = JSON.stringify(buildIntakePayload(DEMO, INS, CONSENTS, SID));
    expect(blob).not.toContain("policy_holder");
  });

  it("sends the SSN as bare digits", () => {
    const payload = buildIntakePayload(DEMO, INS, CONSENTS, SID);
    expect(payload.demographics.ssn).toBe("000000000");
  });

  it("attaches the submission identifier as a declared root field (e5b-SPEC-3/4)", () => {
    // fe-attempt-identifier (contract half): submission_id is a declared root
    // key, and the built payload carries exactly the value handed in.
    expect(CONTRACT.request_fields.root).toContain("submission_id");
    const payload = buildIntakePayload(DEMO, INS, CONSENTS, SID);
    expect(payload.submission_id).toBe(SID);
  });
});

const UUID4_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

describe("newSubmissionId mint (e5b-SPEC-17/18)", () => {
  it("mints a version-4 UUID via crypto.randomUUID", () => {
    // fe-mint-independent: the id is drawn from a CSPRNG, not from any form
    // field — the randomness guarantee lives at the mint (e5b-D-9).
    expect(newSubmissionId()).toMatch(UUID4_RE);
  });

  it("mints a distinct id on every call — never reused across registrations", () => {
    // fe-fresh-per-registration: 200 mints, all distinct and all v4.
    const ids = new Set(Array.from({ length: 200 }, () => newSubmissionId()));
    expect(ids.size).toBe(200);
    for (const id of ids) expect(id).toMatch(UUID4_RE);
  });

  it("falls back to getRandomValues when randomUUID is unavailable", () => {
    // A non-secure context may lack randomUUID but not getRandomValues; the
    // fallback still yields a version-4, variant-correct UUID.
    const real = globalThis.crypto;
    const shim = {
      getRandomValues: (a: Uint8Array) => real.getRandomValues(a),
    } as unknown as Crypto;
    try {
      Object.defineProperty(globalThis, "crypto", { value: shim, configurable: true });
      const id = newSubmissionId();
      expect(id).toMatch(UUID4_RE);
    } finally {
      Object.defineProperty(globalThis, "crypto", { value: real, configurable: true });
    }
  });
});
