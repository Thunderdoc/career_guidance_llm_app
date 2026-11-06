"use client";

/**
 * /start wizard (Phase 1.5): persona → skills/interests → constraints → goal.
 * Guest-first: submits to the anonymous, rate-limited POST /recommend and
 * routes to /report/[runId]. The draft autosaves to localStorage; the full
 * response is kept in sessionStorage so the (guest) report page can render
 * it without a session. Constraints travel as the additive `constraints`
 * object on the recommend request and are stored on the run.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ProfileInput } from "@/lib/types";
import { Stepper } from "./ui/stepper";
import { ErrorNote, Spinner } from "./ui";

const DRAFT_KEY = "cg.startDraft.v1";
const PERSONAS = [
  { id: "school", key: "p1_persona_school", experience: "Student / No experience" },
  { id: "college", key: "p1_persona_college", experience: "Student / No experience" },
  { id: "fresher", key: "p1_persona_fresher", experience: "Junior (0-2 years)" },
  { id: "switcher", key: "p1_persona_switcher", experience: "Mid-level (2-5 years)" },
] as const;
const BUDGETS = ["p1_budget_free", "p1_budget_low", "p1_budget_mid", "p1_budget_high"] as const;
const GOALS = [
  { id: "job_6_months", key: "p1_goal_job" },
  { id: "higher_studies", key: "p1_goal_study" },
  { id: "explore", key: "p1_goal_explore" },
] as const;

type Draft = {
  persona: string;
  skills: string;
  interests: string;
  education: string;
  resumeText: string;
  city: string;
  relocate: boolean;
  hours: number;
  budget: string;
  language: string;
  goalType: string;
};

const EMPTY: Draft = {
  persona: "college", skills: "", interests: "", education: "", resumeText: "",
  city: "", relocate: false, hours: 6, budget: "p1_budget_free", language: "en", goalType: "job_6_months",
};

export function StartWizard() {
  const { t } = useI18n();
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [resumeNote, setResumeNote] = useState("");
  const loaded = useRef(false);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(DRAFT_KEY);
      if (raw) setDraft({ ...EMPTY, ...(JSON.parse(raw) as Partial<Draft>) });
    } catch { /* fresh draft */ }
    loaded.current = true;
  }, []);

  useEffect(() => {
    if (loaded.current) window.localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  }, [draft]);

  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));
  const steps = [t("p1_step_persona"), t("p1_step_skills"), t("p1_step_constraints"), t("p1_step_goal")];
  const persona = PERSONAS.find((p) => p.id === draft.persona) ?? PERSONAS[1];

  const onSkillsChange = (value: string) => {
    set({ skills: value });
    const last = value.split(",").pop()?.trim() ?? "";
    if (last.length >= 2) {
      api.suggestSkills(last).then((r) => setSuggestions(r.suggestions)).catch(() => setSuggestions([]));
    } else setSuggestions([]);
  };

  const onResume = async (file: File) => {
    setResumeNote("");
    try {
      const res = await api.extractResume(file);
      set({ resumeText: res.text, skills: draft.skills || res.skills.join(", ") });
    } catch {
      // /resume/extract stays signed-in only in Phase 1 — say so plainly.
      setResumeNote(t("p1_resume_signin_note"));
    }
  };

  const submit = async () => {
    setBusy(true); setError("");
    const body: ProfileInput = {
      skills: draft.skills,
      interests: draft.interests,
      education: draft.education,
      experience_level: persona.experience,
      goals: draft.goalType,
      resume_text: draft.resumeText,
      constraints: {
        persona: draft.persona,
        city: draft.city,
        relocate: draft.relocate,
        hours_per_week: draft.hours,
        budget_range: t(draft.budget as never),
        language: draft.language,
        goal_type: draft.goalType,
      },
    };
    try {
      const res = await api.recommend(body);
      if (res.run_id) {
        try { window.sessionStorage.setItem(`cg.report.${res.run_id}`, JSON.stringify(res)); } catch { /* private mode */ }
        router.push(`/report/${res.run_id}`);
      } else setError(t("error_generic"));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("error_generic"));
    } finally { setBusy(false); }
  };

  const radioCls = (active: boolean) =>
    `flex min-h-[44px] w-full items-center gap-3 rounded-xl border px-4 py-3 text-left text-sm transition ${active ? "border-accent/60 bg-white/[0.05]" : "border-white/10 hover:bg-white/[0.03]"}`;

  return (
    <div className="mx-auto w-full max-w-2xl px-5 pb-20">
      <header className="py-6"><Link href="/" className="font-serif text-xl">Career Guidance AI</Link></header>
      <h1 className="font-serif text-3xl">{t("p1_start_title")}</h1>
      <p className="mt-2 text-sm text-fg-2">{t("p1_start_sub")}</p>
      <div className="mt-6"><Stepper steps={steps} current={step} /></div>
      <p className="mt-2 text-xs text-fg-3">{t("p1_draft_saved")}</p>

      <div className="mt-8">
        {step === 0 && (
          <fieldset>
            <legend className="font-serif text-xl">{t("p1_persona_q")}</legend>
            <div className="mt-4 space-y-3">
              {PERSONAS.map((p) => (
                <label key={p.id} className={radioCls(draft.persona === p.id)}>
                  <input type="radio" name="persona" className="accent-[#00d4aa]" checked={draft.persona === p.id} onChange={() => set({ persona: p.id })} />
                  {t(p.key)}
                </label>
              ))}
            </div>
          </fieldset>
        )}

        {step === 1 && (
          <div className="space-y-5">
            <div>
              <label htmlFor="wz-skills" className="font-serif text-xl">{t("skills_label")}</label>
              <input id="wz-skills" value={draft.skills} onChange={(e) => onSkillsChange(e.target.value)}
                placeholder="Python, SQL, Excel" className="mt-3 w-full rounded-xl border border-white/15 bg-transparent px-4 py-3 text-sm outline-none focus:border-accent/60" />
              {suggestions.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {suggestions.map((s) => (
                    <button key={s} type="button" className="rounded-full border border-white/15 px-3 py-1.5 text-xs hover:bg-white/5"
                      onClick={() => set({ skills: draft.skills ? `${draft.skills.replace(/,[^,]*$/, "")}${draft.skills.includes(",") ? ", " : ""}${s}` : s })}>{s}</button>
                  ))}
                </div>
              )}
            </div>
            <div>
              <label htmlFor="wz-interests" className="text-sm text-fg-2">{t("interests")}</label>
              <input id="wz-interests" value={draft.interests} onChange={(e) => set({ interests: e.target.value })}
                placeholder={t("p1_interests_ph")} className="mt-2 w-full rounded-xl border border-white/15 bg-transparent px-4 py-3 text-sm outline-none focus:border-accent/60" />
              <a href="/explore?tab=discover" className="mt-2 inline-block text-sm text-accent underline decoration-dotted">{t("p1_quiz_link")}</a>
            </div>
            <div>
              <label htmlFor="wz-education" className="text-sm text-fg-2">{t("education")}</label>
              <input id="wz-education" value={draft.education} onChange={(e) => set({ education: e.target.value })}
                placeholder={t("education_ph")} className="mt-2 w-full rounded-xl border border-white/15 bg-transparent px-4 py-3 text-sm outline-none focus:border-accent/60" />
            </div>
            <div>
              <label htmlFor="wz-resume" className="text-sm text-fg-2">{t("attach_resume")}</label>
              <input id="wz-resume" type="file" accept=".pdf,.txt,.md" className="mt-2 block w-full text-sm"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) void onResume(f); }} />
              {resumeNote && <p className="mt-2 text-sm text-gold">{resumeNote}</p>}
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-5">
            <div>
              <label htmlFor="wz-city" className="text-sm text-fg-2">{t("p1_city")}</label>
              <input id="wz-city" value={draft.city} onChange={(e) => set({ city: e.target.value })}
                placeholder={t("p1_city_ph")} className="mt-2 w-full rounded-xl border border-white/15 bg-transparent px-4 py-3 text-sm outline-none focus:border-accent/60" />
            </div>
            <label className={radioCls(draft.relocate)}>
              <input type="checkbox" className="accent-[#00d4aa]" checked={draft.relocate} onChange={(e) => set({ relocate: e.target.checked })} />
              {t("p1_relocate")}
            </label>
            <div>
              <label htmlFor="wz-hours" className="text-sm text-fg-2">{t("p1_hours")}: <span className="font-semibold text-fg">{draft.hours}</span></label>
              <input id="wz-hours" type="range" min={1} max={40} value={draft.hours} onChange={(e) => set({ hours: Number(e.target.value) })} className="mt-2 w-full" />
            </div>
            <fieldset>
              <legend className="text-sm text-fg-2">{t("p1_budget")}</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {BUDGETS.map((b) => (
                  <label key={b} className={radioCls(draft.budget === b)}>
                    <input type="radio" name="budget" className="accent-[#00d4aa]" checked={draft.budget === b} onChange={() => set({ budget: b })} />
                    {t(b)}
                  </label>
                ))}
              </div>
            </fieldset>
            <div>
              <label htmlFor="wz-lang" className="text-sm text-fg-2">{t("p1_language_pref")}</label>
              <select id="wz-lang" value={draft.language} onChange={(e) => set({ language: e.target.value })}
                className="mt-2 w-full rounded-xl border border-white/15 bg-transparent px-4 py-3 text-sm outline-none">
                <option value="en">English</option><option value="ta">தமிழ்</option><option value="hi">हिन्दी</option>
              </select>
            </div>
          </div>
        )}

        {step === 3 && (
          <fieldset>
            <legend className="font-serif text-xl">{t("p1_goal_q")}</legend>
            <div className="mt-4 space-y-3">
              {GOALS.map((g) => (
                <label key={g.id} className={radioCls(draft.goalType === g.id)}>
                  <input type="radio" name="goal" className="accent-[#00d4aa]" checked={draft.goalType === g.id} onChange={() => set({ goalType: g.id })} />
                  {t(g.key)}
                </label>
              ))}
            </div>
          </fieldset>
        )}
      </div>

      <div className="mt-6"><ErrorNote error={error} /></div>
      <div className="mt-4 flex items-center justify-between gap-3">
        <button type="button" disabled={step === 0 || busy} onClick={() => setStep((s) => Math.max(0, s - 1))}
          className="min-h-[44px] rounded-xl border border-white/15 px-5 py-3 text-sm font-medium transition hover:bg-white/5 disabled:opacity-40">{t("p1_back")}</button>
        {step < 3 ? (
          <button type="button" onClick={() => setStep((s) => Math.min(3, s + 1))}
            className="min-h-[44px] rounded-xl bg-white px-6 py-3 text-sm font-medium text-black transition hover:bg-white/90">{t("p1_next")}</button>
        ) : (
          <button type="button" disabled={busy || draft.skills.trim().length < 3} onClick={() => void submit()}
            className="min-h-[44px] rounded-xl bg-white px-6 py-3 text-sm font-medium text-black transition hover:bg-white/90 disabled:opacity-40">
            {busy ? t("connecting") : t("p1_submit")}
          </button>
        )}
      </div>
      {busy && <Spinner label={t("step_match")} />}
    </div>
  );
}
