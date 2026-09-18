export type Market = {
  currency: string;
  salary_p25: number | null;
  salary_p50: number | null;
  salary_p75: number | null;
  postings_30d: number | null;
  trend: "up" | "flat" | "down" | "unknown";
  source: string;
};

export type Resource = { skill: string; title: string; url: string; provider: string; free: boolean };

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
  description: string;
  job_zone: number;
  transition_path: string[];
  market: Market | null;
  resources: Resource[];
  provenance: Record<string, unknown>;
};

export type RecommendResponse = {
  run_id: number | null;
  provider: string;
  is_demo: boolean;
  used_fallback: boolean;
  priority_skills: string[];
  detected_skills: string[];
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
export type AssessmentResult = {
  scores: Record<string, number>;
  holland_code: string;
  profile: { dim: string; name: string; score: number; blurb: string }[];
};
