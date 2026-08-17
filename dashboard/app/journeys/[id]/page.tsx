"use client";

import { use, useEffect, useState } from "react";
import { decideApproval, getJourney, uploadDocument, type Journey } from "@/lib/api";

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

export default function JourneyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [journey, setJourney] = useState<Journey | null>(null);

  async function refresh() {
    try {
      setJourney(await getJourney(id));
    } catch {
      /* keep polling */
    }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (!journey) return <p>Loading…</p>;

  const pending = (journey.approvals ?? []).filter((a) => a.status === "pending");

  return (
    <>
      <div className="card">
        <span className={`status-pill ${journey.status}`}>{journey.status.replace("_", " ")}</span>
        <h2 style={{ margin: "0.5rem 0" }}>{journey.goal}</h2>
        <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>
          {journey.requirements.map((r) => (
            <li key={r.id} style={{ fontSize: "0.9rem", marginBottom: "0.25rem" }}>
              <strong>{r.title}</strong> — {r.form} via {r.authority}{" "}
              {r.registration_number ? `✅ ${r.registration_number}` : `(${r.status})`}
            </li>
          ))}
        </ul>
      </div>

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
            <li key={i}>
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
