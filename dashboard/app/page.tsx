"use client";

import { useEffect, useState } from "react";
import { createJourney, listJourneys, type Journey } from "@/lib/api";

export default function Home() {
  const [journeys, setJourneys] = useState<Journey[]>([]);
  const [goal, setGoal] = useState(
    "Make my home food business legal so I can sell on delivery platforms"
  );
  const [busy, setBusy] = useState(false);

  async function refresh() {
    try {
      setJourneys(await listJourneys());
    } catch {
      /* API not up yet — keep polling */
    }
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2500);
    return () => clearInterval(t);
  }, []);

  async function onCreate() {
    setBusy(true);
    try {
      const { journey_id } = await createJourney(goal, {
        applicant_name: "Meera Shah",
        city: "Ahmedabad",
        premises: "residential",
        annual_turnover_inr: 800000,
      });
      window.location.href = `/journeys/${journey_id}`;
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="card">
        <h2>What paperwork can I take off your plate?</h2>
        <textarea rows={2} value={goal} onChange={(e) => setGoal(e.target.value)} />
        <button onClick={onCreate} disabled={busy || !goal.trim()}>
          {busy ? "Starting…" : "Start my journey"}
        </button>
      </div>

      {journeys.map((j) => (
        <a key={j.id} href={`/journeys/${j.id}`} style={{ textDecoration: "none", color: "inherit" }}>
          <div className="card">
            <span className={`status-pill ${j.status}`}>{j.status.replace("_", " ")}</span>
            <p style={{ margin: "0.5rem 0 0" }}>{j.goal}</p>
          </div>
        </a>
      ))}
    </>
  );
}
