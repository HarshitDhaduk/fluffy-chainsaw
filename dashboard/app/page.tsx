"use client";

import { useEffect, useState } from "react";
import { createJourney, listJourneys, type Journey } from "@/lib/api";

const GOAL_PRESETS = [
  "Make my home food business legal so I can sell on delivery platforms",
  "Register my freelance design studio",
  "Open a small boutique and sell online",
];

const CHANNEL_OPTIONS = ["Delivery platforms", "Direct orders", "E-commerce", "In person"];

type Profile = {
  applicant_name: string;
  city: string;
  business: string;
  annual_turnover_inr: number | "";
  premises: "residential" | "commercial";
  channels: string[];
  demo_documents: boolean;
};

const EMPTY_PROFILE: Profile = {
  applicant_name: "",
  city: "",
  business: "",
  annual_turnover_inr: "",
  premises: "residential",
  channels: ["Delivery platforms"],
  demo_documents: false,
};

function IntakeWizard() {
  const [step, setStep] = useState(0);
  const [goal, setGoal] = useState(GOAL_PRESETS[0]);
  const [profile, setProfile] = useState<Profile>(EMPTY_PROFILE);
  const [busy, setBusy] = useState(false);

  const set = (patch: Partial<Profile>) => setProfile((p) => ({ ...p, ...patch }));

  async function submit() {
    setBusy(true);
    try {
      const { journey_id } = await createJourney(goal, {
        ...profile,
        annual_turnover_inr: profile.annual_turnover_inr || undefined,
        channels: profile.channels.map((c) => c.toLowerCase()),
      });
      window.location.href = `/journeys/${journey_id}`;
    } finally {
      setBusy(false);
    }
  }

  const steps = ["Your goal", "About you", "Your business", "Review"];

  return (
    <div className="card">
      <div className="wizard-steps">
        {steps.map((label, i) => (
          <span key={label} className={`wizard-step ${i === step ? "active" : i < step ? "done" : ""}`}>
            {i < step ? "✓ " : `${i + 1}. `}
            {label}
          </span>
        ))}
      </div>

      {step === 0 && (
        <>
          <h2>What paperwork can I take off your plate?</h2>
          <div style={{ marginBottom: "0.75rem" }}>
            {GOAL_PRESETS.map((g) => (
              <button
                key={g}
                className={`chip ${goal === g ? "chip-active" : ""}`}
                onClick={() => setGoal(g)}
              >
                {g.length > 44 ? g.slice(0, 42) + "…" : g}
              </button>
            ))}
          </div>
          <textarea rows={2} value={goal} onChange={(e) => setGoal(e.target.value)} />
        </>
      )}

      {step === 1 && (
        <>
          <h2>About you</h2>
          <label>Your name (exactly as printed on your PAN card)</label>
          <input
            value={profile.applicant_name}
            placeholder="e.g. Meera Shah"
            onChange={(e) => set({ applicant_name: e.target.value })}
          />
          <label>City</label>
          <input
            value={profile.city}
            placeholder="e.g. Ahmedabad"
            onChange={(e) => set({ city: e.target.value })}
          />
        </>
      )}

      {step === 2 && (
        <>
          <h2>Your business</h2>
          <label>What do you make or do?</label>
          <input
            value={profile.business}
            placeholder="e.g. Home kitchen — Gujarati snacks"
            onChange={(e) => set({ business: e.target.value })}
          />
          <label>Expected annual turnover (₹) — this decides your license tier</label>
          <input
            type="number"
            value={profile.annual_turnover_inr}
            placeholder="e.g. 800000"
            onChange={(e) =>
              set({ annual_turnover_inr: e.target.value === "" ? "" : Number(e.target.value) })
            }
          />
          <label>Where do you operate from?</label>
          <div style={{ marginBottom: "0.75rem" }}>
            {(["residential", "commercial"] as const).map((p) => (
              <button
                key={p}
                className={`chip ${profile.premises === p ? "chip-active" : ""}`}
                onClick={() => set({ premises: p })}
              >
                {p === "residential" ? "Home / residential" : "Commercial premises"}
              </button>
            ))}
          </div>
          <label>How will you sell?</label>
          <div>
            {CHANNEL_OPTIONS.map((c) => (
              <button
                key={c}
                className={`chip ${profile.channels.includes(c) ? "chip-active" : ""}`}
                onClick={() =>
                  set({
                    channels: profile.channels.includes(c)
                      ? profile.channels.filter((x) => x !== c)
                      : [...profile.channels, c],
                  })
                }
              >
                {c}
              </button>
            ))}
          </div>
        </>
      )}

      {step === 3 && (
        <>
          <h2>Ready to go</h2>
          <p style={{ fontSize: "0.95rem" }}>
            <strong>{profile.applicant_name || "You"}</strong>
            {profile.city ? ` (${profile.city})` : ""} — {profile.business || "your business"},
            selling via {profile.channels.join(", ").toLowerCase() || "—"}, from{" "}
            {profile.premises} premises
            {profile.annual_turnover_inr
              ? `, ~₹${Number(profile.annual_turnover_inr).toLocaleString("en-IN")}/year`
              : ""}
            .
          </p>
          <p style={{ fontSize: "0.9rem", color: "var(--muted)" }}>
            LalFita will research which registrations apply, ask for your documents, check them
            for rejection traps, and chase every application to approval. You approve each
            outbound step with one tap.
          </p>
          <label style={{ display: "block", margin: "0.75rem 0" }}>
            <input
              type="checkbox"
              checked={profile.demo_documents}
              onChange={(e) => set({ demo_documents: e.target.checked })}
            />{" "}
            Demo mode: use sample documents instead of my uploads
          </label>
        </>
      )}

      <div style={{ marginTop: "1rem", display: "flex", gap: "0.5rem" }}>
        {step > 0 && (
          <button className="secondary" onClick={() => setStep(step - 1)}>
            Back
          </button>
        )}
        {step < 3 ? (
          <button onClick={() => setStep(step + 1)} disabled={step === 0 && !goal.trim()}>
            Next
          </button>
        ) : (
          <button onClick={submit} disabled={busy || !goal.trim()}>
            {busy ? "Starting…" : "Start my journey"}
          </button>
        )}
      </div>
    </div>
  );
}

export default function Home() {
  const [journeys, setJourneys] = useState<Journey[]>([]);

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

  return (
    <>
      <IntakeWizard />
      {journeys.length > 0 && <h3>Your journeys</h3>}
      {journeys.map((j) => (
        <a key={j.id} href={`/journeys/${j.id}`} style={{ textDecoration: "none", color: "inherit" }}>
          <div className="card">
            <span className={`status-pill ${j.status}`}>{j.status.replace(/_/g, " ")}</span>
            <p style={{ margin: "0.5rem 0 0" }}>{j.goal}</p>
          </div>
        </a>
      ))}
    </>
  );
}
