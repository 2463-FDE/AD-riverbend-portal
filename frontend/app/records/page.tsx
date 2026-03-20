"use client";

import { useState } from "react";

interface RecordItem {
  id: number;
  kind: string;
  body: string;
}
interface EncounterBlock {
  encounter: { id: number; type: string; provider: string; summary: string };
  records: RecordItem[];
}

export default function RecordsPage() {
  // The records view loads by patient id straight off the URL/input. The id is
  // a sequential integer and the backend does not check ownership (IDOR — see
  // docs/handover/portal.har).
  const [patientId, setPatientId] = useState("1042");
  const [data, setData] = useState<EncounterBlock[] | null>(null);
  const [status, setStatus] = useState("");

  async function load() {
    setStatus("Loading…");
    try {
      const res = await fetch(`/api/records?patient_id=${patientId}`);
      const json = await res.json();
      setData(json.encounters ?? []);
      setStatus("");
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "error");
    }
  }

  return (
    <div>
      <h1>My Records</h1>
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input
          value={patientId}
          onChange={(e) => setPatientId(e.target.value)}
          style={{ padding: 8, border: "1px solid #ccc", borderRadius: 4 }}
        />
        <button onClick={load} style={{ padding: "8px 16px" }}>
          Load
        </button>
      </div>
      {status && <p>{status}</p>}
      {data?.map((block) => (
        <div
          key={block.encounter.id}
          style={{
            background: "white",
            padding: 16,
            borderRadius: 6,
            marginBottom: 12,
            border: "1px solid #e0e6ed",
          }}
        >
          <strong>
            {block.encounter.type} — {block.encounter.provider}
          </strong>
          <p>{block.encounter.summary}</p>
          {block.records.map((r) => (
            <div key={r.id} style={{ fontSize: 14, color: "#445" }}>
              [{r.kind}] {r.body}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
