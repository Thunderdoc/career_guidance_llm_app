export type Market = {
  currency: string;
  salary_p25: number | null;
  salary_p50: number | null;
  salary_p75: number | null;
  postings_30d: number | null;
  trend: "up" | "flat" | "down" | "unknown";
  source: string;
  trend_label?: string;
  remote_friendly?: boolean;
};

export type Resource = {
  skill: string;
  title: string;
  url: string;
  provider: string;
  free: boolean;
  level?: string;
  language?: string;
  duration_minutes?: number;
  id?: number;
};

export type Recommendation = {
  title: string;
  match_reason: string;
  suitability: "beginner" | "intermediate" | "advanced";
  matching_skills: string[];
  missing_skills: string[];
  learning_path: string[];
  next_steps: string[];
  career_id: string;
  match_score: number;
  match_percent: number;
  readiness: number;
  demand: string;
  description: string;
  job_zone: number;
  transition_path: string[];
  market: Market | null;
  resources: Resource[];
  provenance: Record<string, unknown>;
  why: string[];
  score_parts: { skills: number; interests: number; job_zone: number };
};

export type RecommendResponse = {
  run_id: number | null;
  provider: string;
  is_demo: boolean;
  used_fallback: boolean;
  priority_skills: string[];
  detected_skills: string[];
  unmatched_skills: string[];
  weights: { skills: number; interests: number; job_zone: number };
  recommendations: Recommendation[];
};

export type ProfileInput = {
  skills: string;
  interests: string;
  education: string;
  experience_level: string;
  goals: string;
  resume_text: string;
  interests_profile?: Record<string, number> | null;
  country?: string;
};

export type HistoryRun = {
  id: number;
  created_at: string;
  provider: string;
  is_demo: boolean;
  skills: string;
  goals: string;
  experience_level: string;
  recommendations: Recommendation[];
};

export type Question = { id: string; dim: string; text: string };
export type DiscoverItem = { id: string; dim: string; text: string; weight: number; active: boolean; locale: string };

export type AssessmentResult = {
  scores: Record<string, number>;
  holland_code: string;
  profile: { dim: string; name: string; score: number; blurb: string }[];
  answered?: number;
  total?: number;
};

export type AssessmentHistoryItem = {
  id: number;
  created_at: string;
  holland_code: string;
  scores: Record<string, number>;
};

export type Profile = {
  user_id: string;
  persona: string;
  education: string;
  current_role: string;
  experience_level: string;
  skills: string[];
  goals: string;
  interests: string;
  hours_per_week: number;
  language: string;
  country: string;
  onboarded: boolean;
  updated_at: string;
};

export type ReadinessResult = {
  career_id: string;
  title: string;
  readiness: number;
  readiness_weighted: number;
  counts: { strong: number; weak: number; missing: number };
  skills: {
    skill: string;
    importance: number;
    rating: number;
    status: "strong" | "weak" | "missing";
  }[];
  radar: { skill: string; rating: number; importance: number }[];
  template: string;
  source: string;
};

export type RoadmapItem = {
  id: string;
  week: number;
  week_label?: string;
  skill: string;
  title: string;
  status: string;
  hours: number;
  importance?: number;
  done?: boolean;
  prerequisite_of: string[];
  resources: Resource[];
  milestone: string;
  source?: string;
};

export type RoadmapResult = {
  plan_id: number;
  career_id: string;
  title: string;
  hours_per_week: number;
  weeks: number;
  eta: string;
  readiness_before: number;
  readiness_after: number;
  items: RoadmapItem[];
  milestones: { week: number; text: string }[];
  missing_skills: string[];
  weak_skills: string[];
  source: string;
  created_at: string;
};

export type PlanResult = RoadmapResult & { ratings: Record<string, number> };

export type TransitionStep = {
  id: string;
  title: string;
  job_zone: number;
  delta_skills: string[];
  shared_skills: string[];
  salary_p50?: number | null;
};

export type TransitionResult = {
  from: { id: string; title: string };
  to: { id: string; title: string };
  hops: number;
  found: boolean;
  path: TransitionStep[];
  steps: TransitionStep[];
  delta_skills: string[];
  total_delta_skills: string[];
  source: string;
  note: string;
};

export type CareerDetail = {
  id: string;
  title: string;
  description: string;
  job_zone: number;
  skills: string[];
  knowledge: string[];
  technology: string[];
  hot_technology: string[];
  alt_titles: string[];
  holland_code: string;
  interests: Record<string, number>;
  related: { id: string; title: string; job_zone: number }[];
  market: Market;
  market_us?: Market;
  tasks: { text: string; source: string }[];
  skill_importance: { skill: string; importance: number }[];
  education_path: { level: string; typical: string; source: string }[];
  resources: Resource[];
  transitions_in: { id: string; title: string; delta_skills?: string[]; shared_skills?: string[] }[];
  family: string;
  remote: boolean;
  demand_label?: string;
  salary_band_in?: string;
  indian_titles?: string[];
  ladder?: {
    entry_points: import("./api").LadderRung[];
    step_across: import("./api").LadderRung[];
    step_up: import("./api").LadderRung[];
    source: string;
  };
};

export type CompareResult = {
  careers: CareerDetail[];
  shared_skills: string[];
  unique_skills: { id: string; title: string; skills: string[] }[];
  table: { label: string; values: (string | number)[] }[];
};

export type InterviewQuestion = {
  id: string;
  kind: "behavioural" | "technical";
  question: string;
  hint: string;
  star: { situation: string; task: string; action: string; result: string };
};

export type InterviewKit = {
  career_id: string;
  title: string;
  seed: number;
  questions: InterviewQuestion[];
  source: string;
};

export type LearnResource = {
  id: number;
  skill: string;
  title: string;
  url: string;
  provider: string;
  level: string;
  language: string;
  free: boolean;
  duration_minutes: number;
  status?: string;
  last_checked?: string;
  uses?: number;
  saved?: boolean;
  done?: boolean;
};

export type ResumeScore = {
  score: number;
  grade: string;
  target_career: { id: string; title: string } | null;
  keyword_coverage: { matched: string[]; missing: string[]; percent: number };
  action_verbs: { found: string[]; percent: number };
  quantified_impact: { bullets: number; quantified: number; percent: number; examples: string[] };
  sections: { name: string; found: boolean }[];
  detected_years: number;
  job_zone_fit: number;
  missing_keywords: string[];
  rewrites: { original: string; suggestion: string; reason: string }[];
  source: string;
};

export type XpStatus = {
  xp: number;
  level: number;
  level_name: string;
  counts?: Record<string, number>;
  streak: { current: number; longest: number; days: string[] };
  badges: { id: string; name: string; description: string; earned_at: string }[];
  next_badge: { id: string; name: string; description: string } | null;
  recent: { kind: string; points: number; created_at: string; detail: string }[];
};

export type FeedbackItem = {
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
  /** Present on the /announcements payload (shared shape keeps the client small). */
  announcements?: { id: number; title: string; body: string; level: string; pinned: boolean; created_at: string }[];
};
