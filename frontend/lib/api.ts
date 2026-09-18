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
