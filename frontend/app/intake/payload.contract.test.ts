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

// The identifier is minted by the page (once per mount) and passed in, so the
// contract test supplies a fixed one: what it asserts is that the builder emits
// the declared root key, not how the value is produced.
const SUBMISSION_ID = "6f1d1a2e-6e0f-4a3c-9a4c-0f8a5b2d7c31";

const BLANK_INS: InsuranceForm = {
  carrier: "",
  member_id: "",
  group_number: "",
  plan_type: "",
  policy_holder_is_self: true,
};

function expected(object: string): string[] {
  const omitted = new Set(CONTRACT.portal_omits[object] ?? []);
  return CONTRACT.request_fields[object].filter((f) => !omitted.has(f)).sort();
}

describe("POST /intake payload contract (portal side)", () => {
  it("sends exactly the declared root keys", () => {
    const payload = buildIntakePayload(DEMO, INS, CONSENTS, SUBMISSION_ID);
    expect(Object.keys(payload).sort()).toEqual(expected("root"));
  });

  it("sends exactly the declared demographics keys, minus the declared omissions", () => {
    const payload = buildIntakePayload(DEMO, INS, CONSENTS, SUBMISSION_ID);
    expect(Object.keys(payload.demographics).sort()).toEqual(expected("demographics"));
  });

  it("sends exactly the declared insurance keys", () => {
    const payload = buildIntakePayload(DEMO, INS, CONSENTS, SUBMISSION_ID);
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
      SUBMISSION_ID,
    );
    expect(payload.consents).toEqual(["treatment_consent", "npp_ack", "communications_opt_in"]);
  });

  it("sends one combined name, not first_name/last_name", () => {
    const payload = buildIntakePayload(DEMO, INS, CONSENTS, SUBMISSION_ID);
    expect(payload.demographics.name).toBe("Sample Patient");
    expect(JSON.stringify(payload)).not.toContain("first_name");
  });

  it("sends insurance: null when every insurance field is blank, keeping the root key", () => {
    const payload = buildIntakePayload(DEMO, BLANK_INS, CONSENTS, SUBMISSION_ID);
    expect(payload.insurance).toBeNull();
    expect("insurance" in payload).toBe(true);
  });

  it("sends nothing policy-holder-shaped (E4-SPEC-3)", () => {
    const blob = JSON.stringify(buildIntakePayload(DEMO, INS, CONSENTS, SUBMISSION_ID));
    expect(blob).not.toContain("policy_holder");
  });

  it("sends the SSN as bare digits", () => {
    const payload = buildIntakePayload(DEMO, INS, CONSENTS, SUBMISSION_ID);
    expect(payload.demographics.ssn).toBe("000000000");
  });
});

describe("submission identifier", () => {
  it("mints a UUIDv4, with the version and variant bits set", () => {
    // The service validates the value as a UUID and rejects anything else with
    // a 422 (E5-SPEC-40), so the shape is a contract, not a formatting choice.
    expect(newSubmissionId()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
  });

  it("mints a distinct value on every call", () => {
    const ids = new Set(Array.from({ length: 50 }, () => newSubmissionId()));
    expect(ids.size).toBe(50);
  });

  it("still mints a well-formed UUIDv4 without crypto.randomUUID", () => {
    // randomUUID is secure-context-only and the portal is not guaranteed to be
    // served over https, so the fallback is a real path, not decoration: if it
    // were broken, plain-http deployments would send a malformed identifier and
    // every registration would 422.
    const patchable = crypto as unknown as { randomUUID?: () => string };
    const original = patchable.randomUUID;
    patchable.randomUUID = undefined;
    try {
      expect(newSubmissionId()).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
      );
    } finally {
      patchable.randomUUID = original;
    }
  });
});
