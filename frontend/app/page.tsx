"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Card from "./components/Card";
import StatusBadge from "./components/StatusBadge";
import {
  IconCalendar,
  IconLab,
  IconIntake,
  IconRecords,
  IconRoi,
  IconClock,
  IconPin,
  IconStethoscope,
  IconHeart,
} from "./components/icons";
import { apiFetch, getUser } from "./lib/session";
import type { Appointment, EncounterBlock, RecordItem } from "./lib/types";
import { fmtDateTime, firstName } from "./lib/format";

// The dashboard pulls a default patient's data so the portal has something to
// show on landing (a single-patient demo account).
const DEFAULT_PATIENT_ID = "1042";

// Fixed, client-authored, non-PHI. The dashboard is the landing surface, so an
// outage rendered as "you have none" is the first thing a user reads
// (E5-SPEC-5, E5-SPEC-6).
const APPTS_UNAVAILABLE =
  "Appointments could not be loaded. This is not a statement that there are none scheduled — " +
  "retry, or open the appointments page.";
const RESULTS_UNAVAILABLE =
  "Recent results could not be loaded. This is not a statement that there are none on file — " +
  "retry, or open the records page.";

// The appointments read answers either a bare array or {items: [...]}. Anything
// else — including the {"detail": ...} body a converted gateway sends on
// failure — is a failed load, not an empty one.
function listOf(d: unknown): unknown[] | null {
  if (Array.isArray(d)) return d;
  const items = (d as { items?: unknown } | null)?.items;
  return Array.isArray(items) ? items : null;
}

function isResult(r: RecordItem): boolean {
  return Boolean(r.test || r.value !== undefined || r.reference_range);
}

export default function DashboardPage() {
  const [appts, setAppts] = useState<Appointment[] | null>(null);
  const [results, setResults] = useState<RecordItem[] | null>(null);
  // Three states per panel, not two: null = loading, Failed = could not load,
  // [] = genuinely empty.
  const [apptsFailed, setApptsFailed] = useState(false);
  const [resultsFailed, setResultsFailed] = useState(false);
  const [name, setName] = useState("there");

  useEffect(() => {
    const u = getUser();
    if (u?.full_name) setName(firstName(u.full_name));

    apiFetch(`/api/appointments?patient_id=${DEFAULT_PATIENT_ID}`)
      .then(async (r) => {
        if (!r.ok) {
          setApptsFailed(true);
          return;
        }
        const items = listOf(await r.json());
        if (!items) {
          setApptsFailed(true);
          return;
        }
        setAppts(items as Appointment[]);
      })
      .catch(() => setApptsFailed(true));   // never setAppts([])

    apiFetch(`/api/records?patient_id=${DEFAULT_PATIENT_ID}`)
      .then(async (r) => {
        if (!r.ok) {
          setResultsFailed(true);
          return;
        }
        const d: unknown = await r.json();
        const encounters = (d as { encounters?: unknown } | null)?.encounters;
        if (!Array.isArray(encounters)) {
          setResultsFailed(true);
          return;
        }
        const recs = (encounters as EncounterBlock[])
          .flatMap((e) => e.records ?? [])
          .filter(isResult);
        setResults(recs.slice(0, 5));
      })
      .catch(() => setResultsFailed(true));
  }, []);

  const upcoming = (appts ?? [])
    .filter((a) => !["cancelled", "canceled", "completed"].includes(a.status?.toLowerCase()))
    .sort((a, b) => (a.start_at ?? "").localeCompare(b.start_at ?? ""));
  const next = upcoming[0];

  return (
    <div className="rb-stack">
      <div className="rb-page-head">
        <h1>Good day, {name}</h1>
        <p>Here&apos;s a summary of your care at Riverbend Community Health.</p>
      </div>

      <div className="rb-grid rb-grid--2">
        {/* Next appointment */}
        <Card title="Next appointment" icon={<IconCalendar />}
          action={<Link href="/appointments">View all</Link>}>
          {apptsFailed ? (
            <div className="rb-alert rb-alert--err" role="status">{APPTS_UNAVAILABLE}</div>
          ) : appts === null ? (
            <Loading label="Loading appointments…" />
          ) : next ? (
            <div>
              <div className="rb-listrow__title" style={{ fontSize: "1.05rem" }}>
                {next.reason || "Office visit"}
              </div>
              <div className="rb-listrow__meta" style={{ marginTop: 6 }}>
                <span><IconStethoscope width={15} height={15} /> {next.provider}</span>
                <span><IconClock width={15} height={15} /> {fmtDateTime(next.start_at)}</span>
                {next.location && <span><IconPin width={15} height={15} /> {next.location}</span>}
              </div>
              <div style={{ marginTop: 12 }}>
                <StatusBadge status={next.status} />
              </div>
            </div>
          ) : (
            <div className="rb-empty">
              No upcoming appointments.
              <div style={{ marginTop: 10 }}>
                <Link className="rb-btn rb-btn--primary rb-btn--sm" href="/appointments">
                  Schedule a visit
                </Link>
              </div>
            </div>
          )}
        </Card>

        {/* Recent results */}
        <Card title="Recent results" icon={<IconLab />}
          action={<Link href="/records">View records</Link>}>
          {resultsFailed ? (
            <div className="rb-alert rb-alert--err" role="status">{RESULTS_UNAVAILABLE}</div>
          ) : results === null ? (
            <Loading label="Loading results…" />
          ) : results.length ? (
            <table className="rb-table">
              <thead>
                <tr>
                  <th>Test</th>
                  <th>Value</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => (
                  <tr key={r.id}>
                    <td>{r.test || r.kind}</td>
                    <td className="rb-table__num">
                      {r.value ?? "—"}
                      {r.unit ? ` ${r.unit}` : ""}
                    </td>
                    <td><StatusBadge status={r.status || "normal"} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="rb-empty">No recent lab results on file.</div>
          )}
        </Card>
      </div>

      {/* Quick actions */}
      <div>
        <h2 style={{ marginBottom: 14 }}>Quick actions</h2>
        <div className="rb-grid rb-grid--4">
          <Tile href="/intake" icon={<IconIntake />} title="Start Intake"
            sub="Complete new-patient forms" />
          <Tile href="/records" icon={<IconRecords />} title="View Records"
            sub="Encounters & lab results" />
          <Tile href="/roi" icon={<IconRoi />} title="Request Records"
            sub="Release of information" />
          <Tile href="/appointments" icon={<IconCalendar />} title="Schedule"
            sub="Find an open appointment" />
        </div>
      </div>

      <Card title="Your care team" icon={<IconHeart />}>
        <p className="rb-muted" style={{ margin: 0 }}>
          Riverbend Community Health — Primary Care &amp; Specialty Clinics. For urgent
          medical concerns, call 911. For portal help, call (555) 014-2200.
        </p>
      </Card>
    </div>
  );
}

function Tile({
  href,
  icon,
  title,
  sub,
}: {
  href: string;
  icon: React.ReactNode;
  title: string;
  sub: string;
}) {
  return (
    <Link href={href} className="rb-tile">
      <span className="rb-tile__icon">{icon}</span>
      <span className="rb-tile__title">{title}</span>
      <span className="rb-tile__sub">{sub}</span>
    </Link>
  );
}

function Loading({ label }: { label: string }) {
  return (
    <div className="rb-loading">
      <span className="rb-spinner rb-spinner--dark" aria-hidden="true" /> {label}
    </div>
  );
}
