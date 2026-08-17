"use client";

import { use, useEffect, useState } from "react";
import {
  decideApproval,
  getJourney,
  uploadDocument,
  type Deadline,
  type Journey,
} from "@/lib/api";

const DOC_LABELS: Record<string, string> = {
  pan: "PAN card",
  aadhaar: "Aadhaar card",
  utility_bill: "Electricity bill",
};

function DocumentSlot({
  journeyId,
  kind,
  journey,
  onDone,
}: {
  journeyId: string;
  kind: string;
  journey: Journey;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const doc = journey.documents.find((d) => d.kind === kind);
  const blocking = doc?.issues.some((i) => i.severity === "blocking");

  async function onPick(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    try {
      await uploadDocument(journeyId, kind, file);
      onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ marginBottom: "0.75rem" }}>
      <strong>{DOC_LABELS[kind] ?? kind}</strong>{" "}
      {doc ? (blocking ? "⚠️ needs a corrected upload" : "✅ " + doc.filename) : "— not uploaded"}
      {doc?.issues.map((i, n) => (
        <p key={n} style={{ fontSize: "0.85rem", margin: "0.25rem 0", color: "#92400e" }}>
          {i.detail}
        </p>
      ))}
      <div>
        <input
          type="file"
          accept="image/*,.pdf"
          disabled={busy}
          onChange={(e) => onPick(e.target.files?.[0])}
        />
      </div>
    </div>
  );
}

function CountdownCard({ deadline, now }: { deadline: Deadline; now: number }) {
  const due = new Date(deadline.due_at).getTime();
  const created = new Date(deadline.created_at).getTime();
  const total = Math.max(due - created, 1);
  const remaining = due - now;
  const fraction = Math.max(remaining / total, 0);
  const urgency = remaining <= 0 ? "overdue" : fraction < 0.25 ? "critical" : fraction < 0.5 ? "warning" : "ok";

  const abs = Math.abs(remaining);
  const d = Math.floor(abs / 86400000);
  const h = Math.floor((abs % 86400000) / 3600000);
  const m = Math.floor((abs % 3600000) / 60000);
  const s = Math.floor((abs % 60000) / 1000);
  const clock = d > 0 ? `${d}d ${h}h ${m}m` : `${h}h ${m}m ${s}s`;

  return (
    <div className={`countdown ${urgency}`}>
      <div className="countdown-clock">
        {remaining <= 0 ? `⛔ overdue by ${clock}` : `⏳ ${clock} left`}
      </div>
      <div style={{ fontSize: "0.85rem" }}>{deadline.label}</div>
      <div className="countdown-track">
        <div className="countdown-fill" style={{ width: `${Math.min(fraction, 1) * 100}%` }} />
      </div>
    </div>
  );
}

export default function JourneyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [journey, setJourney] = useState<Journey | null>(null);
  const [now, setNow] = useState(() => Date.now());

  async function refresh() {
    try {
      setJourney(await getJourney(id));
    } catch {
      /* keep polling */
    }
  }

  useEffect(() => {
    refresh();
    const poll = setInterval(refresh, 2000);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(tick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!journey) return <p>Loading…</p>;

  const pending = (journey.approvals ?? []).filter((a) => a.status === "pending");
  const activeDeadlines = (journey.deadlines ?? []).filter((d) => !d.resolved);
  const done = journey.requirements.filter((r) => r.status === "done").length;
  const total = journey.requirements.length;

  return (
    <>
      <div className="card">
        <span className={`status-pill ${journey.status}`}>{journey.status.replace(/_/g, " ")}</span>
        <h2 style={{ margin: "0.5rem 0" }}>{journey.goal}</h2>
        {total > 0 && (
          <>
            <div className="progress-track" title={`${done}/${total} registrations granted`}>
              <div className="progress-fill" style={{ width: `${(done / total) * 100}%` }} />
            </div>
            <ul style={{ margin: "0.75rem 0 0", paddingLeft: "1.2rem" }}>
              {journey.requirements.map((r) => (
                <li key={r.id} style={{ fontSize: "0.9rem", marginBottom: "0.25rem" }}>
                  <strong>{r.title}</strong> — {r.form} via {r.authority}{" "}
                  {r.registration_number ? `✅ ${r.registration_number}` : `(${r.status.replace(/_/g, " ")})`}
                  <div style={{ color: "var(--muted)", fontSize: "0.8rem" }}>{r.why}</div>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {activeDeadlines.length > 0 && (
        <div className="card" style={{ borderColor: "#f59e0b" }}>
          <h3 style={{ marginTop: 0 }}>Ticking clocks the Sentinel is watching</h3>
          {activeDeadlines.map((d) => (
            <CountdownCard key={d.id} deadline={d} now={now} />
          ))}
        </div>
      )}

      {journey.required_documents.length > 0 && journey.status !== "completed" && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Documents</h3>
          {journey.required_documents.map((kind) => (
            <DocumentSlot
              key={kind}
              journeyId={journey.id}
              kind={kind}
              journey={journey}
              onDone={refresh}
            />
          ))}
        </div>
      )}

      {pending.length > 0 && (
        <div className="card" style={{ borderColor: "#f59e0b" }}>
          <h3 style={{ marginTop: 0 }}>Needs your one-tap approval</h3>
          {pending.map((a) => (
            <div key={a.id} style={{ marginBottom: "0.75rem" }}>
              <p style={{ margin: "0 0 0.5rem", fontSize: "0.9rem" }}>{a.summary}</p>
              <button onClick={() => decideApproval(a.id, true).then(refresh)}>Approve</button>{" "}
              <button className="secondary" onClick={() => decideApproval(a.id, false).then(refresh)}>
                Reject
              </button>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>What your agents have been doing</h3>
        <ul className="timeline">
          {(journey.timeline ?? []).map((t, i) => (
            <li key={i} className={`actor-${t.actor}`}>
              <span className="actor">{t.actor}</span>
              {t.detail}
              <span className="ts">{new Date(t.ts).toLocaleTimeString()}</span>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
