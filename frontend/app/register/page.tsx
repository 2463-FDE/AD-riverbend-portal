"use client";

import { useState } from "react";

export default function RegisterPage() {
  const [form, setForm] = useState({
    name: "",
    dob: "",
    ssn: "",
    insurance_id: "",
    address: "",
    phone: "",
  });
  const [status, setStatus] = useState<string>("");
  const [busy, setBusy] = useState(false);

  function update(field: string, value: string) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setStatus("Saving… this can take a few seconds.");
    // Calls our API route, which proxies to the gateway/intake-service.
    // Registration "spins" ~4-5s before it confirms (see RIV-088).
    const res = await fetch("/api/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    const data = await res.json();
    setBusy(false);
    setStatus(
      data.patient_id
        ? `Registered. Patient ID ${data.patient_id}.`
        : `Could not register: ${data.error ?? "unknown error"}`
    );
  }

  return (
    <div>
      <h1>New Patient Registration</h1>
      <form onSubmit={submit} style={{ display: "grid", gap: 12, maxWidth: 420 }}>
        {(
          [
            ["name", "Full name"],
            ["dob", "Date of birth"],
            ["ssn", "SSN"],
            ["insurance_id", "Insurance ID"],
            ["address", "Address"],
            ["phone", "Phone"],
          ] as const
        ).map(([field, label]) => (
          <label key={field} style={{ display: "grid", gap: 4 }}>
            <span>{label}</span>
            <input
              value={(form as Record<string, string>)[field]}
              onChange={(e) => update(field, e.target.value)}
              style={{ padding: 8, border: "1px solid #ccc", borderRadius: 4 }}
            />
          </label>
        ))}
        <button
          type="submit"
          disabled={busy}
          style={{
            padding: "10px 16px",
            background: "#0b5d8a",
            color: "white",
            border: "none",
            borderRadius: 4,
            cursor: busy ? "wait" : "pointer",
          }}
        >
          {busy ? "Saving…" : "Save"}
        </button>
      </form>
      {status && <p style={{ marginTop: 16 }}>{status}</p>}
    </div>
  );
}
