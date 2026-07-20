"use client";

import { useState } from "react";
import Link from "next/link";
import Card from "../components/Card";
import { apiFetch } from "../lib/session";
import { formatSsn, formatPhone, digitsOnly } from "../lib/format";

interface Demographics {
  first_name: string;
  last_name: string;
  dob: string;
  gender: string;
  ssn: string;
  phone: string;
  email: string;
  address: string;
}
interface Insurance {
  carrier: string;
  member_id: string;
  group_number: string;
  plan_type: string;
  policy_holder: string;
}
interface Consents {
  treatment: boolean;
  privacy: boolean;
  financial: boolean;
  communications: boolean;
}

const STEPS = ["Demographics", "Insurance", "Consents", "Review & Submit"];

export default function IntakePage() {
  const [step, setStep] = useState(0);
  const [demo, setDemo] = useState<Demographics>({
    first_name: "",
    last_name: "",
    dob: "",
    gender: "",
    ssn: "",
    phone: "",
    email: "",
    address: "",
  });
  const [ins, setIns] = useState<Insurance>({
    carrier: "",
    member_id: "",
    group_number: "",
    plan_type: "",
    policy_holder: "",
  });
  const [consents, setConsents] = useState<Consents>({
    treatment: false,
    privacy: false,
    financial: false,
    communications: false,
  });

  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState<string | null>(null);
  const [instructions, setInstructions] = useState<{
    items: string[];
    disclaimer: string;
  } | null>(null);

  const consentsOk = consents.treatment && consents.privacy;
  const demoOk = demo.first_name && demo.last_name && demo.dob;

  function next() {
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  }
  function back() {
    setStep((s) => Math.max(s - 1, 0));
  }

  async function submit() {
    setBusy(true);
    setResult(null);
    // Combined payload: demographics + insurance + consents.
    // SSN is display-formatted (F2) but sent as bare digits — a 9-digit SSN
    // loses no meaning. Phone is sent as-is: dashes are only readability and
    // any country code / extension the patient typed must survive to storage
    // (formatPhone leaves those verbatim), so we do NOT collapse it to digits.
    const payload = {
      demographics: {
        ...demo,
        ssn: digitsOnly(demo.ssn),
        phone: demo.phone.trim(),
      },
      insurance: ins,
      consents,
    };
    try {
      // NOTE: /api/intake is intentionally slow (~4-5s, RIV-088) — it "spins"
      // before confirming. See app/api/intake/route.ts.
      const res = await apiFetch("/api/intake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || data?.error) {
        setResult({ ok: false, text: data?.error || "Submission failed." });
      } else {
        setResult({
          ok: true,
          text: data.patient_id
            ? `Intake submitted. Your patient ID is ${data.patient_id}.`
            : "Intake submitted successfully.",
        });
      }
    } catch {
      setResult({ ok: false, text: "Could not reach the portal. Please try again." });
    } finally {
      setBusy(false);
    }
  }

  // Ask the AI assistant for a visit-prep checklist. The payload is
  // deliberately administrative facts only (booleans + the plan-type select) —
  // no name, DOB, SSN, or any typed-in text is ever sent to this endpoint.
  async function fetchInstructions() {
    setAiBusy(true);
    setAiError(null);
    // Insurance facts must be internally consistent — the assistant rejects a
    // contradictory pair (e.g. has_insurance=false with an insured plan type).
    // An explicit Self-pay selection wins; otherwise any insurance signal —
    // a selected plan type, carrier, or member ID — counts as insured.
    const planType = ins.plan_type || null;
    const hasInsurance =
      planType === "Self-pay"
        ? false
        : Boolean(planType || ins.carrier || ins.member_id);
    try {
      const res = await apiFetch("/api/ai/intake-instructions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          has_insurance: hasInsurance,
          plan_type: planType,
          policy_holder_is_self: !ins.policy_holder,
          communications_opt_in: consents.communications,
          financial_ack: consents.financial,
        }),
      });
      const data = await res.json();
      if (!res.ok || !Array.isArray(data?.items)) {
        setAiError("Could not prepare your checklist right now. Please try again later.");
      } else {
        setInstructions({ items: data.items, disclaimer: data.disclaimer ?? "" });
      }
    } catch {
      setAiError("Could not reach the portal. Please try again later.");
    } finally {
      setAiBusy(false);
    }
  }

  if (result?.ok) {
    return (
      <div className="rb-stack">
        <div className="rb-page-head">
          <h1>New Patient Intake</h1>
        </div>
        <Card>
          <div className="rb-alert rb-alert--ok" role="status" style={{ marginBottom: 16 }}>
            {result.text}
          </div>
          <p className="rb-muted">
            Thank you. Riverbend front-desk staff will review your intake before your first visit.
          </p>
          <Link className="rb-btn rb-btn--primary" href="/">
            Back to dashboard
          </Link>
        </Card>
        <Card title="Prepare for your first visit">
          {!instructions && (
            <>
              <p className="rb-muted">
                Get a short, personalized checklist of what to bring and how to prepare.
              </p>
              {aiError && (
                <div className="rb-alert rb-alert--err" role="alert" style={{ marginBottom: 12 }}>
                  {aiError}
                </div>
              )}
              <button
                className="rb-btn rb-btn--primary"
                type="button"
                onClick={fetchInstructions}
                disabled={aiBusy}
              >
                {aiBusy ? (
                  <><span className="rb-spinner" aria-hidden="true" /> Preparing your checklist…</>
                ) : (
                  "Get visit prep instructions"
                )}
              </button>
            </>
          )}
          {instructions && (
            <>
              <ul>
                {instructions.items.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
              {instructions.disclaimer && (
                <p className="rb-muted" style={{ marginTop: 12 }}>
                  {instructions.disclaimer}
                </p>
              )}
            </>
          )}
        </Card>
      </div>
    );
  }

  return (
    <div className="rb-stack">
      <div className="rb-page-head">
        <h1>New Patient Intake</h1>
        <p>Complete the four steps below. It only takes a few minutes.</p>
      </div>

      <ol className="rb-steps" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
        {STEPS.map((label, i) => {
          const state = i === step ? "active" : i < step ? "done" : "todo";
          return (
            <li
              key={label}
              className={`rb-steps__item${state !== "todo" ? ` rb-steps__item--${state}` : ""}`}
              aria-current={state === "active" ? "step" : undefined}
            >
              <span className="rb-steps__num">{state === "done" ? "✓" : i + 1}</span>
              <span className="rb-steps__label">{label}</span>
            </li>
          );
        })}
      </ol>

      {result && !result.ok && (
        <div className="rb-alert rb-alert--err" role="alert">
          {result.text}
        </div>
      )}

      <Card title={STEPS[step]}>
        {step === 0 && (
          <fieldset style={{ border: "none", margin: 0, padding: 0 }}>
            <legend className="rb-muted" style={{ marginBottom: 12 }}>
              Tell us who you are.
            </legend>
            <div className="rb-field-row">
              <Field id="first_name" label="First name" required value={demo.first_name}
                autoComplete="given-name"
                onChange={(v) => setDemo({ ...demo, first_name: v })} />
              <Field id="last_name" label="Last name" required value={demo.last_name}
                autoComplete="family-name"
                onChange={(v) => setDemo({ ...demo, last_name: v })} />
            </div>
            <div className="rb-field-row">
              <Field id="dob" label="Date of birth" type="date" required value={demo.dob}
                onChange={(v) => setDemo({ ...demo, dob: v })} />
              <SelectField id="gender" label="Gender" value={demo.gender}
                onChange={(v) => setDemo({ ...demo, gender: v })}
                options={["", "Female", "Male", "Non-binary", "Prefer not to say"]} />
            </div>
            <div className="rb-field-row">
              <Field id="ssn" label="SSN" hint="Used for insurance verification only."
                value={demo.ssn} format={formatSsn} inputMode="numeric"
                autoComplete="off" maxLength={11} revealable
                onChange={(v) => setDemo({ ...demo, ssn: v })} />
              <Field id="phone" label="Phone" type="tel" value={demo.phone}
                format={formatPhone} inputMode="tel" autoComplete="tel"
                onChange={(v) => setDemo({ ...demo, phone: v })} />
            </div>
            <Field id="email" label="Email" type="email" value={demo.email}
              inputMode="email" autoComplete="email"
              onChange={(v) => setDemo({ ...demo, email: v })} />
            <Field id="address" label="Home address" value={demo.address}
              autoComplete="street-address"
              onChange={(v) => setDemo({ ...demo, address: v })} />
          </fieldset>
        )}

        {step === 1 && (
          <fieldset style={{ border: "none", margin: 0, padding: 0 }}>
            <legend className="rb-muted" style={{ marginBottom: 12 }}>
              Enter your primary insurance.
            </legend>
            <div className="rb-field-row">
              <Field id="carrier" label="Insurance carrier" value={ins.carrier}
                onChange={(v) => setIns({ ...ins, carrier: v })} />
              <Field id="member_id" label="Member / Insurance ID" value={ins.member_id}
                onChange={(v) => setIns({ ...ins, member_id: v })} />
            </div>
            <div className="rb-field-row">
              <Field id="group_number" label="Group number" value={ins.group_number}
                onChange={(v) => setIns({ ...ins, group_number: v })} />
              <SelectField id="plan_type" label="Plan type" value={ins.plan_type}
                onChange={(v) => setIns({ ...ins, plan_type: v })}
                options={["", "HMO", "PPO", "EPO", "POS", "Medicare", "Medicaid", "Self-pay"]} />
            </div>
            <Field id="policy_holder" label="Policy holder name"
              hint="Leave blank if you are the policy holder."
              value={ins.policy_holder} onChange={(v) => setIns({ ...ins, policy_holder: v })} />
          </fieldset>
        )}

        {step === 2 && (
          <fieldset style={{ border: "none", margin: 0, padding: 0 }}>
            <legend className="rb-muted" style={{ marginBottom: 12 }}>
              Please review and acknowledge the following. Items marked required must be accepted.
            </legend>
            <Consent id="c_treatment" required checked={consents.treatment}
              onChange={(v) => setConsents({ ...consents, treatment: v })}
              title="Consent to treatment"
              body="I consent to medical care and treatment provided by Riverbend Community Health." />
            <Consent id="c_privacy" required checked={consents.privacy}
              onChange={(v) => setConsents({ ...consents, privacy: v })}
              title="Notice of privacy practices (HIPAA)"
              body="I acknowledge receipt of the Notice of Privacy Practices describing how my health information may be used and disclosed." />
            <Consent id="c_financial" checked={consents.financial}
              onChange={(v) => setConsents({ ...consents, financial: v })}
              title="Financial responsibility"
              body="I understand I am financially responsible for charges not covered by my insurance." />
            <Consent id="c_comms" checked={consents.communications}
              onChange={(v) => setConsents({ ...consents, communications: v })}
              title="Electronic communications (optional)"
              body="I agree to receive appointment reminders and portal notifications by email or text." />
          </fieldset>
        )}

        {step === 3 && (
          <div>
            <p className="rb-muted">Please confirm your information before submitting.</p>
            <h3 style={{ marginTop: 18 }}>Demographics</h3>
            <ReviewBlock rows={[
              ["Name", `${demo.first_name} ${demo.last_name}`.trim() || "—"],
              ["Date of birth", demo.dob || "—"],
              ["Gender", demo.gender || "—"],
              ["SSN", demo.ssn ? `•••-••-${digitsOnly(demo.ssn).slice(-4)}` : "—"],
              ["Phone", demo.phone || "—"],
              ["Email", demo.email || "—"],
              ["Address", demo.address || "—"],
            ]} />
            <h3 style={{ marginTop: 18 }}>Insurance</h3>
            <ReviewBlock rows={[
              ["Carrier", ins.carrier || "—"],
              ["Member ID", ins.member_id || "—"],
              ["Group number", ins.group_number || "—"],
              ["Plan type", ins.plan_type || "—"],
              ["Policy holder", ins.policy_holder || "Self"],
            ]} />
            <h3 style={{ marginTop: 18 }}>Consents</h3>
            <ReviewBlock rows={[
              ["Treatment", consents.treatment ? "Accepted" : "Not accepted"],
              ["Privacy (HIPAA)", consents.privacy ? "Accepted" : "Not accepted"],
              ["Financial responsibility", consents.financial ? "Accepted" : "Declined"],
              ["Electronic communications", consents.communications ? "Accepted" : "Declined"],
            ]} />
          </div>
        )}

        <div className="rb-wizard-actions">
          <button className="rb-btn" onClick={back} disabled={step === 0 || busy} type="button">
            Back
          </button>
          {step < STEPS.length - 1 ? (
            <button
              className="rb-btn rb-btn--primary"
              onClick={next}
              type="button"
              disabled={(step === 0 && !demoOk) || (step === 2 && !consentsOk)}
            >
              Continue
            </button>
          ) : (
            <button
              className="rb-btn rb-btn--primary"
              onClick={submit}
              type="button"
              disabled={busy || !consentsOk || !demoOk}
            >
              {busy ? (
                <><span className="rb-spinner" aria-hidden="true" /> Submitting… this can take a few seconds</>
              ) : (
                "Submit intake"
              )}
            </button>
          )}
        </div>
      </Card>
    </div>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  type = "text",
  required = false,
  hint,
  format,
  inputMode,
  autoComplete,
  maxLength,
  revealable = false,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
  hint?: string;
  format?: (raw: string) => string;
  inputMode?: "text" | "numeric" | "tel" | "email";
  autoComplete?: string;
  maxLength?: number;
  // Render obscured (password-style) with a show/hide toggle — for sensitive
  // fields like SSN, so the value is not shoulder-surfable while typing.
  revealable?: boolean;
}) {
  const [revealed, setRevealed] = useState(false);
  const inputType = revealable ? (revealed ? "text" : "password") : type;
  const input = (
    <input
      id={id}
      className="rb-input"
      type={inputType}
      value={value}
      required={required}
      aria-required={required}
      inputMode={inputMode}
      autoComplete={autoComplete}
      maxLength={maxLength}
      onChange={(e) => onChange(format ? format(e.target.value) : e.target.value)}
    />
  );
  return (
    <div className="rb-field">
      <label className="rb-field__label" htmlFor={id}>
        {label}
        {required && <span className="rb-field__req" aria-hidden="true">*</span>}
      </label>
      {revealable ? (
        <div className="rb-input-reveal">
          {input}
          <button
            type="button"
            className="rb-input-reveal__btn"
            onClick={() => setRevealed((r) => !r)}
            aria-pressed={revealed}
            aria-label={revealed ? `Hide ${label}` : `Show ${label}`}
          >
            {revealed ? "Hide" : "Show"}
          </button>
        </div>
      ) : (
        input
      )}
      {hint && <span className="rb-field__hint">{hint}</span>}
    </div>
  );
}

function SelectField({
  id,
  label,
  value,
  onChange,
  options,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: string[];
}) {
  return (
    <div className="rb-field">
      <label className="rb-field__label" htmlFor={id}>
        {label}
      </label>
      <select id={id} className="rb-select" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o} value={o}>
            {o || "Select…"}
          </option>
        ))}
      </select>
    </div>
  );
}

function Consent({
  id,
  title,
  body,
  checked,
  onChange,
  required = false,
}: {
  id: string;
  title: string;
  body: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  required?: boolean;
}) {
  return (
    <div className="rb-checkbox">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        aria-required={required}
        onChange={(e) => onChange(e.target.checked)}
      />
      <label className="rb-checkbox__body" htmlFor={id}>
        <strong>
          {title}
          {required && <span className="rb-field__req" aria-hidden="true"> *</span>}
        </strong>
        {body}
      </label>
    </div>
  );
}

function ReviewBlock({ rows }: { rows: [string, string][] }) {
  return (
    <div className="rb-review">
      {rows.map(([k, v]) => (
        <div className="rb-review__row" key={k}>
          <span className="rb-review__key">{k}</span>
          <span>{v}</span>
        </div>
      ))}
    </div>
  );
}
