const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080";

export type TimelineEntry = {
  ts: string;
  actor: string;
  event: string;
  detail: string;
};

export type Approval = {
  id: string;
  kind: string;
  summary: string;
  status: "pending" | "approved" | "rejected";
};

export type Requirement = {
  id: string;
  title: string;
  authority: string;
  form: string;
  why: string;
  status: string;
  registration_number: string | null;
};

export type Journey = {
  id: string;
  goal: string;
  status: string;
  requirements: Requirement[];
  timeline?: TimelineEntry[];
  approvals?: Approval[];
};

export async function listJourneys(): Promise<Journey[]> {
  const res = await fetch(`${BASE}/journeys`, { cache: "no-store" });
  return res.json();
}

export async function getJourney(id: string): Promise<Journey> {
  const res = await fetch(`${BASE}/journeys/${id}`, { cache: "no-store" });
  return res.json();
}

export async function createJourney(goal: string, profile: object): Promise<{ journey_id: string }> {
  const res = await fetch(`${BASE}/journeys`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal, profile }),
  });
  return res.json();
}

export async function decideApproval(approvalId: string, approve: boolean): Promise<void> {
  await fetch(`${BASE}/approvals/${approvalId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approve }),
  });
}
