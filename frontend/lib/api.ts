import type { AssessmentResult, HistoryRun, ProfileInput, Question, RecommendResponse } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; ai_mode: boolean; occupations: number; version: string }>("/api/v1/health"),
  meta: () => request<{ experience_levels: string[]; ai_mode: boolean; occupations: number }>("/api/v1/meta"),
  recommend: (body: ProfileInput) => request<RecommendResponse>("/api/v1/recommend", { method: "POST", body: JSON.stringify(body) }),
  extractResume: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${BASE}/api/v1/resume/extract`, { method: "POST", body: form });
    if (!res.ok) throw new Error((await res.json()).detail ?? "Resume could not be read");
    return res.json() as Promise<{ characters: number; text: string; skills: string[] }>;
  },
  suggestSkills: (q: string) => request<{ suggestions: string[] }>(`/api/v1/skills/suggest?q=${encodeURIComponent(q)}`),
  career: (id: string) => request<Record<string, unknown>>(`/api/v1/careers/${encodeURIComponent(id)}`),
  history: () => request<{ runs: HistoryRun[] }>("/api/v1/history"),
  clearHistory: () => request<{ cleared: boolean }>("/api/v1/history", { method: "DELETE" }),
  analytics: () => request<Record<string, unknown>>("/api/v1/analytics"),
  questions: () => request<{ questions: Question[] }>("/api/v1/assessment/questions"),
  assess: (answers: Record<string, number>) => request<AssessmentResult>("/api/v1/assessment", { method: "POST", body: JSON.stringify({ answers }) }),
  jobFit: (skills: string, resume_text: string, job_description: string) =>
    request<{ readiness: number; matched: string[]; missing: string[]; resources: { title: string; url: string; provider: string }[] }>(
      "/api/v1/jobs/fit",
      { method: "POST", body: JSON.stringify({ skills, resume_text, job_description }) },
    ),
  exportUrl: (runId: number, fmt: "md" | "json") => `${BASE}/api/v1/export/${runId}.${fmt}`,
};

export function formatMoney(v: number | null | undefined, currency = "INR") {
  if (v == null) return "—";
  if (currency === "INR") {
    if (v >= 1e7) return `₹${(v / 1e7).toFixed(1)} Cr`;
    if (v >= 1e5) return `₹${(v / 1e5).toFixed(1)} L`;
    return `₹${Math.round(v / 1000)}k`;
  }
  return new Intl.NumberFormat("en", { style: "currency", currency, maximumFractionDigits: 0 }).format(v);
}

// ---- auth / account / admin -------------------------------------------------
export type User = {
  id: string;
  email: string;
  name: string;
  picture: string;
  provider: string;
  role: string;
  is_admin: boolean;
  created_at: string;
  last_login_at: string;
  disabled: boolean;
};

export const auth = {
  me: () => request<{ user: User | null }>("/api/v1/auth/me"),
  providers: () => request<{ google: boolean; magic_link: boolean; email_delivery: boolean }>("/api/v1/auth/providers"),
  magicLink: (email: string, next = "/") =>
    request<{ sent: boolean; dev_link?: string }>("/api/v1/auth/magic-link", { method: "POST", body: JSON.stringify({ email, next }) }),
  googleUrl: (next = "/") => `${BASE}/api/v1/auth/google?next=${encodeURIComponent(next)}`,
  logout: () => request<{ ok: boolean }>("/api/v1/auth/logout", { method: "POST" }),
  myRuns: () => request<{ runs: HistoryRun[] }>("/api/v1/me/runs"),
  progress: () => request<{ done: string[] }>("/api/v1/me/progress"),
  setProgress: (skill: string, done: boolean) =>
    request<{ done: string[] }>("/api/v1/me/progress", { method: "POST", body: JSON.stringify({ skill, done }) }),
  feedback: (body: { rating: number; comment?: string; run_id?: number | null; career_title?: string }) =>
    request<{ id: number }>("/api/v1/me/feedback", { method: "POST", body: JSON.stringify(body) }),
  deleteMe: () => request<{ deleted: boolean }>("/api/v1/me", { method: "DELETE" }),
};

export type AdminOverview = {
  users: { total: number; new_7d: number; active_7d: number };
  runs: { total: number; ai: number; demo: number; anonymous: number; per_day: [string, number][] };
  top_careers: [string, number][];
  top_missing_skills: [string, number][];
  feedback: { total: number; avg_rating: number; open: number };
  system: { version: string; python: string; uptime_s: number; ai_mode: boolean; occupations: number; overrides: number };
};
export type AdminUser = User & { runs: number };
export type Feedback = { id: number; created_at: string; email: string | null; run_id: number | null; career_title: string; rating: number; comment: string; status: string };
export type ResourceRow = { skill: string; overridden: boolean; resources: { title: string; url: string; provider: string; free: boolean }[] };

export const admin = {
  overview: () => request<AdminOverview>("/api/v1/admin/overview"),
  users: (q = "") => request<{ users: AdminUser[] }>(`/api/v1/admin/users?q=${encodeURIComponent(q)}`),
  setRole: (id: string, role: "user" | "admin") => request(`/api/v1/admin/users/${id}/role`, { method: "PATCH", body: JSON.stringify({ role }) }),
  setDisabled: (id: string, disabled: boolean) => request(`/api/v1/admin/users/${id}/disabled`, { method: "PATCH", body: JSON.stringify({ disabled }) }),
  deleteUser: (id: string) => request(`/api/v1/admin/users/${id}`, { method: "DELETE" }),
  runs: () => request<{ runs: { id: number; created_at: string; provider: string; user_id: string | null; skills: string; titles: string[] }[] }>("/api/v1/admin/runs"),
  deleteRun: (id: number) => request(`/api/v1/admin/runs/${id}`, { method: "DELETE" }),
  feedback: (status?: string) => request<{ feedback: Feedback[] }>(`/api/v1/admin/feedback${status ? `?status=${status}` : ""}`),
  setFeedback: (id: number, status: string) => request(`/api/v1/admin/feedback/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),
  resources: (q = "") => request<{ skills: ResourceRow[] }>(`/api/v1/admin/resources?q=${encodeURIComponent(q)}`),
  putResources: (skill: string, resources: ResourceRow["resources"]) =>
    request(`/api/v1/admin/resources/${encodeURIComponent(skill)}`, { method: "PUT", body: JSON.stringify({ resources }) }),
  resetResources: (skill: string) => request(`/api/v1/admin/resources/${encodeURIComponent(skill)}`, { method: "DELETE" }),
  audit: () => request<{ log: { id: number; created_at: string; actor: string; action: string; target: string }[] }>("/api/v1/admin/audit"),
};
