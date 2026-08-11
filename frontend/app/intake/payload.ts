// The portal side of the POST /intake request contract.
//
// A plain module, not part of the page component, for two reasons: the contract
// test (payload.contract.test.ts) can assert the built payload without mounting
// a four-step wizard, and the shape the service receives stops being an inline
// object literal nobody could test. The declaration both ends assert against is
// contracts/intake-registration.json.
//
// What was wrong before: the page sent `demographics.first_name` /
// `demographics.last_name`, `insurance.carrier`, a free-text
// `insurance.policy_holder`, and `consents` as a boolean OBJECT. intake-service
// wants `demographics.name`, `insurance.payer_name`, no policy-holder field at
// all, and `consents` as a list of ConsentKind values — so every submission
// 422'd (docs/debt-log.md "Intake contract break").

// Form key -> the ConsentKind value the service accepts. The five here are the
// whole closed vocabulary; the contract test asserts this map against the
// declaration, which the pytest side asserts against the enum itself.
export const CONSENT_KIND = {
  treatment: "treatment_consent",
  privacy: "npp_ack",
  financial: "financial_responsibility_ack",
  communications: "communications_opt_in",
  roi: "roi_consent",
} as const;

export type ConsentKey = keyof typeof CONSENT_KIND;

export interface DemographicsForm {
  first_name: string;
  last_name: string;
  dob: string;
  gender: string;
  ssn: string;
  phone: string;
  email: string;
  address: string;
}

export interface InsuranceForm {
  carrier: string;
  member_id: string;
  group_number: string;
  plan_type: string;
  policy_holder_is_self: boolean;
}

export type ConsentsForm = Record<ConsentKey, boolean>;

export interface IntakePayload {
  submission_id: string;
  demographics: {
    name: string;
    dob: string | null;
    ssn: string | null;
    gender: string | null;
    address: string | null;
    phone: string | null;
    email: string | null;
    created_via: string;
  };
  insurance: {
    payer_name: string | null;
    member_id: string | null;
    group_number: string | null;
    plan_type: string | null;
  } | null;
  consents: string[];
}

function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * A random identifier for one submission ATTEMPT (E5-SPEC-26, E5-SPEC-38).
 *
 * Random, and derived from nothing the operator typed. A key hashed from
 * SSN/DOB/name would put PHI in a log line, a response body and a stored column
 * at once — and two genuine registrations for one person would collide, which
 * is an accidental master patient index (E5-SPEC-36 exists to keep that from
 * happening).
 *
 * `crypto.randomUUID` is secure-context-only, and this portal is not guaranteed
 * to be served over https, so the fallback is not optional decoration:
 * `getRandomValues` is available either way and the bits it returns are the
 * same quality. The version and variant bits are set by hand because a UUIDv4
 * is what the service validates against.
 */
export function newSubmissionId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40; // version 4
  b[8] = (b[8] & 0x3f) | 0x80; // variant 10x
  const hex = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * Build the POST /intake body from the wizard's three form objects.
 *
 * `notes` is deliberately omitted rather than sent empty — it is a staff field,
 * not a patient-entered one, and the declaration records the omission so the
 * contract test can prove it is an optional field and not a dropped required
 * one. `created_via` is sent explicitly: the service defaults it, but a portal
 * submission that does not say where it came from is indistinguishable from a
 * front-desk one.
 *
 * `submissionId` is taken as an argument rather than minted here: it names the
 * ATTEMPT, not the payload, so every re-submission of one attempt must carry the
 * same value (E5-SPEC-26). Minting per build would hand each retry a fresh
 * identifier and close nothing.
 */
export function buildIntakePayload(
  demo: DemographicsForm,
  ins: InsuranceForm,
  consents: ConsentsForm,
  submissionId: string,
): IntakePayload {
  // Every insurance field blank means no coverage was offered — send null, not
  // an empty object, so a self-pay walk-in does not get an empty coverage row.
  // policy_holder_is_self is a form-only fact: nothing policy-holder-shaped is
  // sent or stored (E4-SPEC-3).
  const insuranceFields = {
    payer_name: orNull(ins.carrier),
    member_id: orNull(ins.member_id),
    group_number: orNull(ins.group_number),
    plan_type: orNull(ins.plan_type),
  };
  const hasInsurance = Object.values(insuranceFields).some((v) => v !== null);

  return {
    submission_id: submissionId,
    demographics: {
      // The 422 the whole defect starts from: the service takes ONE name field.
      name: `${demo.first_name} ${demo.last_name}`.trim(),
      dob: orNull(demo.dob),
      // SSN is display-formatted in the field (F2) but sent as bare digits — a
      // 9-digit SSN loses no meaning. Phone is sent as typed: dashes are only
      // readability, and any country code or extension must survive to storage.
      ssn: orNull(demo.ssn.replace(/\D/g, "")),
      gender: orNull(demo.gender),
      address: orNull(demo.address),
      phone: orNull(demo.phone),
      email: orNull(demo.email),
      created_via: "self_service",
    },
    insurance: hasInsurance ? insuranceFields : null,
    consents: (Object.keys(CONSENT_KIND) as ConsentKey[])
      .filter((key) => consents[key])
      .map((key) => CONSENT_KIND[key]),
  };
}
