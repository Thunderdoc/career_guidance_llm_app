import type {
  AssessmentHistoryItem,
  AssessmentResult,
  CareerDetail,
  CompareResult,
  DiscoverItem,
  FeedbackItem,
  HistoryRun,
  InterviewKit,
  LearnResource,
  PlanResult,
  Profile,
  ProfileInput,
  Question,
  Resource,
  ReadinessResult,
  RecommendResponse,
  ResumeScore,
  RoadmapResult,
  TransitionResult,
  XpStatus,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

/* -------------------------------------------------------------------------- */
/* Transport: cold-start aware fetch with automatic retry                      */
/* -------------------------------------------------------------------------- */

/**
 * Render's free tier sleeps after ~15 minutes idle: the first request then takes
 * 30–60 s (or returns 502/503 while the container boots). `request()` therefore
 * treats timeouts and 502/503/504 as "the server is waking up" and retries
 * instead of surfacing an error, while publishing the state so the UI can show
 * the "Waking up the server…" banner.
 */
export type ServerState = "idle" | "waking" | "ready" | "unreachable";

let serverState: ServerState = "idle";
const stateListeners = new Set<(s: ServerState) => void>();

export function getServerState(): ServerState {
  return serverState;
}

export function onServerState(listener: (s: ServerState) => void): () => void {
  stateListeners.add(listener);
  listener(serverState);
  return () => stateListeners.delete(listener);
}

function setServerState(next: ServerState) {
  if (serverState === next) return;
  serverState = next;
  stateListeners.forEach((l) => l(next));
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public coldStart = false,
  ) {
    super(message);
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const WAKE_STATUSES = new Set([502, 503, 504]);

export type RequestOptions = {
  /** Per-attempt timeout in ms (default 25 s — a cold Render start needs it). */
  timeoutMs?: number;
  /** Extra attempts after the first (default 3 for GETs, 2 for writes). */
  retries?: number;
  /** Milliseconds between attempts (default 4 s, doubling). */
  backoffMs?: number;
  signal?: AbortSignal;
};

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number, signal?: AbortSignal) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

async function request<T>(path: string, init?: RequestInit, opts?: RequestOptions): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const retries = opts?.retries ?? (method === "GET" ? 3 : 2);
  const timeoutMs = opts?.timeoutMs ?? 25_000;
  const backoffMs = opts?.backoffMs ?? 4_000;
  let attempt = 0;

  for (;;) {
    let res: Response;
    try {
      res = await fetchWithTimeout(
        `${BASE}${path}`,
        { headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }, credentials: "include", ...init },
        timeoutMs,
        opts?.signal,
      );
    } catch (e) {
      if (opts?.signal?.aborted) throw e; // caller cancelled — no retry
      if (attempt < retries) {
        setServerState("waking");
        attempt += 1;
        await sleep(backoffMs * attempt);
        continue;
      }
      setServerState("unreachable");
      throw new ApiError(
        "The server could not be reached. It may be starting up — please check your connection and try again.",
        0,
        true,
      );
    }

    if (WAKE_STATUSES.has(res.status) && attempt < retries) {
      setServerState("waking");
      attempt += 1;
      await sleep(backoffMs * attempt);
      continue;
    }

    setServerState("ready");

    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail ?? detail;
      } catch {
        /* not JSON */
      }
      throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail), res.status);
    }
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }
}

/* -------------------------------------------------------------------------- */
/* Helpers                                                                     */
/* -------------------------------------------------------------------------- */

export function formatMoney(v: number | null | undefined, currency = "INR") {
  if (v == null) return "—";
  if (currency === "INR") {
    if (v >= 1e7) return `₹${(v / 1e7).toFixed(1)} Cr`;
    if (v >= 1e5) return `₹${(v / 1e5).toFixed(1)} L`;
    return `₹${Math.round(v / 1000)}k`;
  }
  return new Intl.NumberFormat("en", { style: "currency", currency, maximumFractionDigits: 0 }).format(v);
}

export function downloadFile(name: string, body: string | Blob, type = "text/plain") {
  const blob = typeof body === "string" ? new Blob([body], { type }) : body;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

/* -------------------------------------------------------------------------- */
/* Core API                                                                    */
/* -------------------------------------------------------------------------- */

export const api = {
  health: () =>
    request<{ status: string; ai_mode: boolean; occupations: number; version: string; public_app: boolean }>(
      "/api/v1/health",
    ),
  meta: () =>
    request<{ experience_levels: string[]; ai_mode: boolean; occupations: number; version: string }>("/api/v1/meta"),
  recommend: (body: ProfileInput) =>
    request<RecommendResponse>("/api/v1/recommend", { method: "POST", body: JSON.stringify(body) }),
  compare: (ids: string[], country = "in") =>
    request<CompareResult>(`/api/v1/compare?ids=${ids.map(encodeURIComponent).join(",")}&country=${country}`),
  extractResume: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ characters: number; text: string; skills: string[] }>("/api/v1/resume/extract", {
      method: "POST",
      body: form,
      headers: {}, // let the browser set the multipart boundary
    });
  },
  scoreResume: (body: { resume_text: string; target_career_id?: string; skills?: string }) =>
    request<ResumeScore>("/api/v1/resume/score", { method: "POST", body: JSON.stringify(body) }),
  suggestSkills: (q: string) =>
    request<{ suggestions: string[] }>(`/api/v1/skills/suggest?q=${encodeURIComponent(q)}`),
  searchCareers: (q: string, limit = 12) =>
    request<{ results: { id: string; title: string; job_zone: number }[] }>(
      `/api/v1/careers/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),
  careers: (params: { q?: string; family?: string; job_zone?: number; min_salary?: number; remote?: boolean; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== null) qs.set(k, String(v));
    });
    return request<{ total: number; results: { id: string; title: string; job_zone: number; salary_p50: number | null; demand: string; remote: boolean; family: string }[] }>(
      `/api/v1/careers?${qs.toString()}`,
    );
  },
  career: (id: string, country = "in") =>
    request<CareerDetail>(`/api/v1/careers/${encodeURIComponent(id)}?country=${country}`),
  transitions: (from: string, to: string) =>
    request<TransitionResult>(`/api/v1/transitions?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`),
  history: () => request<{ runs: HistoryRun[] }>("/api/v1/history"),
  clearHistory: () => request<{ cleared: boolean }>("/api/v1/history", { method: "DELETE" }),
  analytics: () => request<Record<string, unknown>>("/api/v1/analytics"),
  questions: () => request<{ questions: Question[] }>("/api/v1/assessment/questions"),
  assess: (answers: Record<string, number>) =>
    request<AssessmentResult>("/api/v1/assessment", { method: "POST", body: JSON.stringify({ answers }) }),
  assessmentHistory: () => request<{ runs: AssessmentHistoryItem[] }>("/api/v1/assessment/history"),
  jobFit: (skills: string, resume_text: string, job_description: string) =>
    request<{
      readiness: number;
      matched: string[];
      missing: string[];
      keywords_to_add: string[];
      resources: LearnResource[];
      score_breakdown: Record<string, number>;
    }>("/api/v1/jobs/fit", {
      method: "POST",
      body: JSON.stringify({ skills, resume_text, job_description }),
    }),
  interview: (careerId: string, seed?: number) =>
    request<InterviewKit>(
      `/api/v1/interview/questions?career_id=${encodeURIComponent(careerId)}${seed !== undefined ? `&seed=${seed}` : ""}`,
    ),
  saveInterview: (body: { career_id: string; seconds: number; notes: Record<string, string> }) =>
    request<{ id: number }>("/api/v1/interview/sessions", { method: "POST", body: JSON.stringify(body) }),
  announcements: () => request<{ announcements: FeedbackItem["announcements"] }>("/api/v1/announcements"),
  feedback: (body: { rating: number; comment?: string; run_id?: number | null; career_title?: string; tool?: string }) =>
    request<{ id: number }>("/api/v1/feedback", { method: "POST", body: JSON.stringify(body) }),
  exportUrl: (runId: number, fmt: "md" | "json") => `${BASE}/api/v1/export/${runId}.${fmt}`,
};

/* -------------------------------------------------------------------------- */
/* Account / journey API                                                       */
/* -------------------------------------------------------------------------- */

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
  runs?: number;
};

export const auth = {
  me: () => request<{ user: User | null }>("/api/v1/auth/me"),
  providers: () =>
    request<{ firebase: boolean; google: boolean; magic_link: boolean; email_delivery: boolean }>(
      "/api/v1/auth/providers",
    ),
  firebase: (id_token: string) =>
    request<{ user: User }>("/api/v1/auth/firebase", { method: "POST", body: JSON.stringify({ id_token }) }),
  magicLink: (email: string, next = "/") =>
    request<{ sent: boolean; dev_link?: string }>("/api/v1/auth/magic-link", {
      method: "POST",
      body: JSON.stringify({ email, next }),
    }),
  googleUrl: (next = "/") => `${BASE}/api/v1/auth/google?next=${encodeURIComponent(next)}`,
  logout: () => request<{ ok: boolean }>("/api/v1/auth/logout", { method: "POST" }),
  myRuns: () => request<{ runs: HistoryRun[] }>("/api/v1/me/runs"),
  progress: () => request<{ done: string[] }>("/api/v1/me/progress"),
  setProgress: (skill: string, done: boolean) =>
    request<{ done: string[] }>("/api/v1/me/progress", { method: "POST", body: JSON.stringify({ skill, done }) }),
  deleteMe: () => request<{ deleted: boolean }>("/api/v1/me", { method: "DELETE" }),
  exportData: () => request<Record<string, unknown>>("/api/v1/me/export"),
  dashboard: () => request<DashboardPayload>("/api/v1/me/dashboard"),
};

export type DashboardPayload = {
  profile: Profile | null;
  target: { career_id: string; title: string; set_at: string } | null;
  readiness: ReadinessResult | null;
  roadmap: RoadmapResult | null;
  xp: XpStatus;
  recent_runs: HistoryRun[];
  announcements: FeedbackItem["announcements"];
  streak: { current: number; longest: number; days: string[] };
};

export const profile = {
  get: () => request<{ profile: Profile | null; options: ProfileOptions }>("/api/v1/profile"),
  save: (body: Partial<Profile>) =>
    request<{ profile: Profile }>("/api/v1/profile", { method: "PUT", body: JSON.stringify(body) }),
};

export type ProfileOptions = {
  personas: string[];
  education_levels: string[];
  experience_levels: string[];
  hours_per_week_range: [number, number];
  languages: string[];
};

export const plan = {
  readiness: (careerId: string) =>
    request<ReadinessResult>(`/api/v1/plan/readiness?career_id=${encodeURIComponent(careerId)}`),
  rate: (careerId: string, ratings: Record<string, number>) =>
    request<ReadinessResult>("/api/v1/plan/ratings", {
      method: "POST",
      body: JSON.stringify({ career_id: careerId, ratings }),
    }),
  generate: (careerId: string, hoursPerWeek = 6) =>
    request<{ plan: PlanResult }>("/api/v1/plan", {
      method: "POST",
      body: JSON.stringify({ career_id: careerId, hours_per_week: hoursPerWeek }),
    }),
  latest: () => request<{ plan: PlanResult | null; ratings: Record<string, number> }>("/api/v1/plan"),
  setItemDone: (planId: number, itemId: string, done: boolean) =>
    request<{ plan: PlanResult }>(`/api/v1/plan/${planId}/items`, {
      method: "PATCH",
      body: JSON.stringify({ item_id: itemId, done }),
    }),
  exportUrl: (planId: number, fmt: "md" | "json" | "ics" | "pdf") => `${BASE}/api/v1/plan/${planId}.${fmt}`,
  target: () => request<{ target: { career_id: string; title: string; set_at: string } | null }>("/api/v1/plan/target"),
  setTarget: (careerId: string) =>
    request<{ target: { career_id: string; title: string; set_at: string } }>("/api/v1/plan/target", {
      method: "POST",
      body: JSON.stringify({ career_id: careerId }),
    }),
};

export const learn = {
  list: (params: { q?: string; skill?: string; language?: string; provider?: string; level?: string; free?: boolean } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== null) qs.set(k, String(v));
    });
    return request<{ results: LearnResource[]; total: number; filters: { skills: string[]; providers: string[]; languages: string[]; levels: string[] } }>(
      `/api/v1/learn?${qs.toString()}`,
    );
  },
  saved: () => request<{ results: LearnResource[] }>("/api/v1/learn/saved"),
  save: (id: number) => request<{ saved: boolean }>(`/api/v1/learn/${id}/save`, { method: "POST" }),
  unsave: (id: number) => request<{ saved: boolean }>(`/api/v1/learn/${id}/save`, { method: "DELETE" }),
  done: (id: number, done: boolean) =>
    request<{ done: boolean; xp: XpStatus }>(`/api/v1/learn/${id}/done`, {
      method: "POST",
      body: JSON.stringify({ done }),
    }),
};

export const discover = {
  items: () => request<{ items: DiscoverItem[]; total: number; scales: Record<string, string> }>("/api/v1/discover/items"),
  submit: (answers: Record<string, number>) =>
    request<AssessmentResult & { history_id: number; top_careers: { id: string; title: string; fit: number; why: string }[] }>(
      "/api/v1/discover",
      { method: "POST", body: JSON.stringify({ answers }) },
    ),
};

export const gamification = {
  status: () => request<XpStatus>("/api/v1/gamification"),
  /** Client-side events that should count toward streaks/badges. */
  event: (kind: string, detail = "") =>
    request<XpStatus>("/api/v1/gamification/event", { method: "POST", body: JSON.stringify({ kind, detail }) }),
};

/* -------------------------------------------------------------------------- */
/* Admin API                                                                   */
/* -------------------------------------------------------------------------- */

export type AdminOverview = {
  users: { total: number; new_7d: number; active_7d: number };
  runs: { total: number; ai: number; offline: number; demo: number; anonymous: number; per_day: [string, number][] };
  tools: [string, number][];
  top_careers: [string, number][];
  top_requested_skills: [string, number][];
  top_missing_skills: [string, number][];
  averages: { match: number; readiness: number };
  feedback: { total: number; avg_rating: number; open: number };
  errors: { count: number; cold_starts: number; recent: { path: string; detail: string; created_at: string }[] };
  system: {
    version: string;
    python: string;
    uptime_s: number;
    ai_mode: boolean;
    occupations: number;
    overrides: number;
    db_bytes: number;
    disk_free_bytes: number;
    firebase: boolean;
    smtp: boolean;
  };
};

export type AdminUserRow = User & { runs: number };
export type AdminRun = {
  id: number;
  created_at: string;
  provider: string;
  is_demo: boolean;
  flagged: boolean;
  user_id: string | null;
  email: string | null;
  tool: string;
  skills: string;
  goals: string;
  job_zone_fit: number;
  titles: string[];
  profile: Record<string, unknown>;
  recommendations: Record<string, unknown>[];
};
export type AdminFeedback = {
  id: number;
  created_at: string;
  email: string | null;
  run_id: number | null;
  career_title: string;
  tool: string;
  rating: number;
  comment: string;
  status: string;
  note: string;
};
export type AdminCareerRow = {
  id: string;
  title: string;
  job_zone: number;
  hidden: boolean;
  custom: boolean;
  family: string;
  salary_p25: number | null;
  salary_p50: number | null;
  salary_p75: number | null;
  trend: string;
  remote: boolean;
  indian_titles: string;
  source: string;
};
export type AdminResource = LearnResource & { status: string; last_checked: string; uses: number; overridden: boolean };
export type AdminUser = AdminUserRow;
export type Feedback = AdminFeedback;
export type ResourceRow = { skill: string; overridden: boolean; resources: Resource[] };
export type AdminSynonym = { alias: string; canonical: string; locale: string; source: string };

export const admin = {
  overview: () => request<AdminOverview>("/api/v1/admin/overview"),
  users: (params: string | { q?: string; sort?: string; order?: string; limit?: number; offset?: number } = {}) => {
    if (typeof params === "string") params = { q: params };
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    });
    return request<{ users: AdminUserRow[]; total: number }>(`/api/v1/admin/users?${qs.toString()}`);
  },
  user: (id: string) => request<{ user: AdminUserRow; runs: AdminRun[]; dashboard: Record<string, unknown> }>(`/api/v1/admin/users/${id}`),
  setRole: (id: string, role: "user" | "admin") =>
    request(`/api/v1/admin/users/${id}/role`, { method: "PATCH", body: JSON.stringify({ role }) }),
  setDisabled: (id: string, disabled: boolean) =>
    request(`/api/v1/admin/users/${id}/disabled`, { method: "PATCH", body: JSON.stringify({ disabled }) }),
  deleteUser: (id: string) => request(`/api/v1/admin/users/${id}`, { method: "DELETE" }),
  exportUsersUrl: () => `${BASE}/api/v1/admin/users.csv`,
  runs: (params: { from?: string; to?: string; user_id?: string; tool?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    });
    return request<{ runs: AdminRun[]; total: number }>(`/api/v1/admin/runs?${qs.toString()}`);
  },
  flagRun: (id: number, flagged: boolean) =>
    request(`/api/v1/admin/runs/${id}/flag`, { method: "PATCH", body: JSON.stringify({ flagged }) }),
  deleteRun: (id: number) => request(`/api/v1/admin/runs/${id}`, { method: "DELETE" }),
  exportRunsUrl: (fmt: "csv" | "json") => `${BASE}/api/v1/admin/runs.${fmt}`,
  careers: (params: { q?: string; hidden?: string; custom?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    });
    return request<{ careers: AdminCareerRow[]; total: number }>(`/api/v1/admin/careers?${qs.toString()}`);
  },
  updateCareer: (id: string, body: Record<string, unknown>) =>
    request(`/api/v1/admin/careers/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
  addCareer: (body: Record<string, unknown>) =>
    request<{ id: string }>("/api/v1/admin/careers", { method: "POST", body: JSON.stringify(body) }),
  importCareers: (csv: string) =>
    request<{ imported: number; skipped: number }>("/api/v1/admin/careers/import", {
      method: "POST",
      body: JSON.stringify({ csv }),
    }),
  exportCareersUrl: () => `${BASE}/api/v1/admin/careers.csv`,
  synonyms: (q = "") => request<{ synonyms: AdminSynonym[] }>(`/api/v1/admin/synonyms?q=${encodeURIComponent(q)}`),
  addSynonym: (body: { alias: string; canonical: string; locale?: string }) =>
    request<{ ok: boolean }>("/api/v1/admin/synonyms", { method: "POST", body: JSON.stringify(body) }),
  deleteSynonym: (alias: string) =>
    request<{ ok: boolean }>(`/api/v1/admin/synonyms/${encodeURIComponent(alias)}`, { method: "DELETE" }),
  unmatched: (limit = 100) => request<{ unmatched: { term: string; count: number; mapped_to: string; last_seen: string }[] }>(`/api/v1/admin/unmatched?limit=${limit}`),
  mapUnmatched: (term: string, canonical: string) =>
    request<{ ok: boolean }>("/api/v1/admin/unmatched/map", { method: "POST", body: JSON.stringify({ term, canonical }) }),
  dismissUnmatched: (term: string) =>
    request<{ ok: boolean }>("/api/v1/admin/unmatched/dismiss", { method: "POST", body: JSON.stringify({ term }) }),
  resources: (q = "") => request<{ resources: AdminResource[] }>(`/api/v1/admin/resources?q=${encodeURIComponent(q)}`),
  upsertResource: (body: Record<string, unknown>, id?: number) =>
    request<{ id: number }>(id === undefined ? "/api/v1/admin/resources" : `/api/v1/admin/resources/${id}`, {
      method: id === undefined ? "POST" : "PUT",
      body: JSON.stringify(body),
    }),
  deleteResource: (id: number) => request(`/api/v1/admin/resources/${id}`, { method: "DELETE" }),
  checkLinks: () => request<{ job_id: number; checked: number; dead: number }>("/api/v1/admin/resources/check", { method: "POST" }),
  exportResourcesUrl: () => `${BASE}/api/v1/admin/resources.yaml`,
  assessmentItems: () => request<{ items: DiscoverItem[] }>("/api/v1/admin/assessment-items"),
  upsertAssessmentItem: (body: { id: string; dim: string; text: string; weight?: number; active?: boolean }) =>
    request<{ ok: boolean }>("/api/v1/admin/assessment-items", { method: "POST", body: JSON.stringify(body) }),
  deleteAssessmentItem: (id: string) => request(`/api/v1/admin/assessment-items/${encodeURIComponent(id)}`, { method: "DELETE" }),
  weights: () => request<{ weights: Record<string, number> }>("/api/v1/admin/weights"),
  setWeights: (weights: Record<string, number>) =>
    request<{ weights: Record<string, number> }>("/api/v1/admin/weights", { method: "PUT", body: JSON.stringify({ weights }) }),
  settings: () => request<{ settings: Record<string, unknown>; flags: Record<string, unknown> }>("/api/v1/admin/settings"),
  setSettings: (values: Record<string, unknown>) =>
    request<{ settings: Record<string, unknown> }>("/api/v1/admin/settings", { method: "PUT", body: JSON.stringify({ values }) }),
  templates: (locale = "en") => request<{ locale: string; templates: Record<string, string>; rendered: Record<string, string> }>(`/api/v1/admin/templates?locale=${locale}`),
  setTemplates: (locale: string, templates: Record<string, string>) =>
    request<{ ok: boolean }>("/api/v1/admin/templates", { method: "PUT", body: JSON.stringify({ locale, templates }) }),
  interviewTemplates: () => request<{ templates: { id: number; kind: string; template: string; active: boolean }[] }>("/api/v1/admin/interview-templates"),
  addInterviewTemplate: (body: { kind: string; template: string }) =>
    request<{ id: number }>("/api/v1/admin/interview-templates", { method: "POST", body: JSON.stringify(body) }),
  deleteInterviewTemplate: (id: number) => request(`/api/v1/admin/interview-templates/${id}`, { method: "DELETE" }),
  feedback: (params: string | { status?: string; rating?: number; tool?: string } = {}) => {
    if (typeof params === "string") params = { status: params };
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "" && v !== null) qs.set(k, String(v));
    });
    return request<{ feedback: AdminFeedback[] }>(`/api/v1/admin/feedback?${qs.toString()}`);
  },
  setFeedback: (id: number, body: { status?: string; note?: string } | string) =>
    request(`/api/v1/admin/feedback/${id}`, {
      method: "PATCH",
      body: JSON.stringify(typeof body === "string" ? { status: body } : body),
    }),
  /** Per-skill curated course overrides (legacy content module, kept while the
   *  full learning-resource CRUD in the console replaces it). */
  skillResources: (q = "") =>
    request<{ skills: ResourceRow[] }>(`/api/v1/admin/resource-overrides?q=${encodeURIComponent(q)}`),
  setSkillResources: (skill: string, resources: Resource[]) =>
    request(`/api/v1/admin/resource-overrides/${encodeURIComponent(skill)}`, {
      method: "PUT",
      body: JSON.stringify({ resources }),
    }),
  resetSkillResources: (skill: string) =>
    request(`/api/v1/admin/resource-overrides/${encodeURIComponent(skill)}`, { method: "DELETE" }),
  announcements: () => request<{ announcements: FeedbackItem["announcements"] }>("/api/v1/admin/announcements"),
  addAnnouncement: (body: { title: string; body: string; level?: string; pinned?: boolean }) =>
    request<{ id: number }>("/api/v1/admin/announcements", { method: "POST", body: JSON.stringify(body) }),
  updateAnnouncement: (id: number, body: Record<string, unknown>) =>
    request(`/api/v1/admin/announcements/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteAnnouncement: (id: number) => request(`/api/v1/admin/announcements/${id}`, { method: "DELETE" }),
  system: () =>
    request<{
      health: { status: string; db: string; firebase: string; smtp: string; ai: string };
      env: { name: string; value: string }[];
      disk: { db_bytes: number; free_bytes: number; total_bytes: number };
      jobs: { id: number; kind: string; status: string; created_at: string; finished_at: string; detail: string }[];
      migrations: { version: number; name: string; applied_at: string }[];
    }>("/api/v1/admin/system"),
  backupUrl: () => `${BASE}/api/v1/admin/backup.db`,
  restore: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ restored: boolean; migrations: number[] }>("/api/v1/admin/restore", {
      method: "POST",
      body: form,
      headers: {},
    });
  },
  clearCache: () => request<{ cleared: boolean }>("/api/v1/admin/cache/clear", { method: "POST" }),
  audit: (limit = 200) =>
    request<{ log: { id: number; created_at: string; actor: string; action: string; target: string; detail: string }[] }>(`/api/v1/admin/audit?limit=${limit}`),
};

export type { FeedbackItem };
