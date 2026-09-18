"use client";

/**
 * Onboarding wizard (5 steps): who you are → education → skills → goal →
 * weekly hours. Saves through `PUT /api/v1/profile` (onboarding: true) and
 * optionally sets the target career.
 */

import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, ArrowRight, Check, Compass, Target } from "lucide-react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, profile as profileApi } from "@/lib/api";
import type { ProfileOptions } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Button, Card, Field, PageHeader, SourceLabel, inputCls } from "./ui";
import { ProgressRing } from "./motion";

const STEPS = ["onb_step_about", "onb_step_edu", "onb_step_skills", "onb_step_goal", "onb_step_plan"] as const;

export function OnboardingWizard() {
  const { t } = useI18n();
  const router = useRouter();
  const [options, setOptions] = useState<ProfileOptions | null>(null);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [skillsQuery, setSkillsQuery] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [careerQuery, setCareerQuery] = useState("");
  const [careers, setCareers] = useState<{ id: string; title: string; job_zone: number }[]>([]);
  const [form, setForm] = useState({
    persona: "",
    education: "",
    current_role: "",
    experience_level: "",
    skills: [] as string[],
    goals: "",
    interests: "",
    hours_per_week: 6,
    language: "en",
    target: "",
  });

  useEffect(() => {
    profileApi
      .get()
      .then((r) => {
        setOptions(r.options);
        if (r.profile) {
          setForm((f) => ({
            ...f,
            persona: r.profile?.persona ?? "",
            education: r.profile?.education ?? "",
            current_role: r.profile?.current_role ?? "",
            experience_level: r.profile?.experience_level ?? "",
            skills: r.profile?.skills ?? [],
            goals: r.profile?.goals ?? "",
            interests: r.profile?.interests ?? "",
            hours_per_week: r.profile?.hours_per_week ?? 6,
            language: r.profile?.language ?? "en",
          }));
        }
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  useEffect(() => {
    if (skillsQuery.trim().length < 2) return setSuggestions([]);
    api
      .suggestSkills(skillsQuery)
      .then((r) => setSuggestions(r.suggestions))
      .catch(() => setSuggestions([]));
  }, [skillsQuery]);

  useEffect(() => {
    if (careerQuery.trim().length < 3) return setCareers([]);
    api
      .searchCareers(careerQuery, 6)
      .then((r) => setCareers(r.results))
      .catch(() => setCareers([]));
  }, [careerQuery]);

  const canAdvance = () => {
    if (step === 0) return Boolean(form.persona && form.experience_level);
    if (step === 1) return Boolean(form.education);
    if (step === 2) return form.skills.length > 0;
    if (step === 3) return form.goals.trim().length > 3;
    return true;
  };

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await profileApi.save({
        persona: form.persona,
        education: form.education,
        current_role: form.current_role,
        experience_level: form.experience_level,
        skills: form.skills,
        goals: form.goals,
        interests: form.interests,
        hours_per_week: form.hours_per_week,
        language: form.language as "en",
        onboarded: true,
        set_target: form.target || undefined,
      } as never);
      if (form.target) {
        await import("@/lib/api").then((m) => m.plan.setTarget(form.target));
      }
      router.push(form.target ? "/plan" : "/recommend");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("onb_title")} subtitle={t("onb_sub")} source={t("onb_source")} />

      <div className="flex items-center gap-4">
        <ProgressRing value={(100 * (step + 1)) / STEPS.length} size={64} stroke={6} label={`${step + 1}/${STEPS.length}`} />
        <div className="flex flex-1 gap-1">
          {STEPS.map((s, i) => (
            <button
              key={s}
              onClick={() => i <= step && setStep(i)}
              className={`flex-1 rounded-full py-1 text-[11px] transition ${
                i === step ? "bg-accent/20 text-accent" : i < step ? "bg-ok/15 text-ok" : "bg-white/5 text-fg-3"
              }`}
            >
              {t(s)}
            </button>
          ))}
        </div>
      </div>

      <Card>
        <AnimatePresence mode="wait">
          <motion.div
            key={step}
            initial={{ opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -24 }}
            transition={{ duration: 0.22 }}
            className="flex flex-col gap-4"
          >
            {step === 0 && (
              <>
                <p className="text-sm text-fg-2">{t("onb_persona_hint")}</p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {(options?.personas ?? []).map((p) => (
                    <button
                      key={p}
                      onClick={() => setForm({ ...form, persona: p })}
                      className={`rounded-xl border p-3 text-left text-sm transition ${
                        form.persona === p ? "border-accent/50 bg-accent/10 text-accent" : "border-white/10 text-fg-2 hover:border-white/20"
                      }`}
                      aria-pressed={form.persona === p}
                    >
                      {p}
                    </button>
                  ))}
                </div>
                <Field label={t("experience")}>
                  <select
                    className={inputCls}
                    value={form.experience_level}
                    onChange={(e) => setForm({ ...form, experience_level: e.target.value })}
                  >
                    <option value="">{t("onb_select")}</option>
                    {(options?.experience_levels ?? []).map((x) => (
                      <option key={x} value={x}>
                        {x}
                      </option>
                    ))}
                  </select>
                </Field>
              </>
            )}

            {step === 1 && (
              <>
                <Field label={t("education")}>
                  <select
                    className={inputCls}
                    value={form.education}
                    onChange={(e) => setForm({ ...form, education: e.target.value })}
                  >
                    <option value="">{t("onb_select")}</option>
                    {(options?.education_levels ?? []).map((x) => (
                      <option key={x} value={x}>
                        {x}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label={t("onb_current_role")} hint={t("onb_current_role_hint")}>
                  <input
                    className={inputCls}
                    value={form.current_role}
                    onChange={(e) => setForm({ ...form, current_role: e.target.value })}
                    placeholder={t("onb_current_role_ph")}
                  />
                </Field>
              </>
            )}

            {step === 2 && (
              <>
                <Field label={t("skills_label")} hint={t("onb_skills_hint")}>
                  <input
                    className={inputCls}
                    value={skillsQuery}
                    onChange={(e) => setSkillsQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && skillsQuery.trim().length > 1) {
                        e.preventDefault();
                        const term = skillsQuery.trim().toLowerCase();
                        if (!form.skills.includes(term)) setForm({ ...form, skills: [...form.skills, term] });
                        setSkillsQuery("");
                        setSuggestions([]);
                      }
                    }}
                    placeholder={t("onb_skills_ph")}
                    aria-describedby="skill-hints"
                  />
                </Field>
                {suggestions.length > 0 && (
                  <div id="skill-hints" className="flex flex-wrap gap-1.5">
                    {suggestions.map((s) => (
                      <button
                        key={s}
                        onClick={() => {
                          if (!form.skills.includes(s)) setForm({ ...form, skills: [...form.skills, s] });
                          setSkillsQuery("");
                          setSuggestions([]);
                        }}
                        className="rounded-full border border-white/10 px-2.5 py-1 text-xs text-fg-2 hover:border-accent/40 hover:text-accent"
                      >
                        + {s}
                      </button>
                    ))}
                  </div>
                )}
                <div className="flex flex-wrap gap-1.5">
                  {form.skills.map((s) => (
                    <span key={s} className="flex items-center gap-1 rounded-full bg-accent/12 px-2.5 py-1 text-xs text-accent">
                      {s}
                      <button onClick={() => setForm({ ...form, skills: form.skills.filter((x) => x !== s) })} aria-label={`remove ${s}`}>
                        ×
                      </button>
                    </span>
                  ))}
                  {form.skills.length === 0 && <p className="text-xs text-fg-3">{t("onb_skills_empty")}</p>}
                </div>
              </>
            )}

            {step === 3 && (
              <>
                <Field label={t("goal")} hint={t("onb_goal_hint")}>
                  <textarea
                    className={inputCls}
                    rows={3}
                    value={form.goals}
                    onChange={(e) => setForm({ ...form, goals: e.target.value })}
                    placeholder={t("onb_goal_ph")}
                  />
                </Field>
                <Field label={t("interests")} hint={t("onb_interests_hint")}>
                  <input
                    className={inputCls}
                    value={form.interests}
                    onChange={(e) => setForm({ ...form, interests: e.target.value })}
                    placeholder={t("interests_ph")}
                  />
                </Field>
                <Field label={t("onb_target")} hint={t("onb_target_hint")}>
                  <input
                    className={inputCls}
                    value={form.target ? `${form.target}` : careerQuery}
                    onChange={(e) => {
                      setCareerQuery(e.target.value);
                      setForm({ ...form, target: "" });
                    }}
                    placeholder={t("onb_target_ph")}
                  />
                </Field>
                {careers.length > 0 && !form.target && (
                  <div className="flex flex-col gap-1">
                    {careers.map((c) => (
                      <button
                        key={c.id}
                        onClick={() => {
                          setForm({ ...form, target: c.id });
                          setCareerQuery(c.title);
                          setCareers([]);
                        }}
                        className="flex items-center gap-2 rounded-lg border border-white/10 px-3 py-2 text-left text-sm text-fg-2 hover:border-accent/40"
                      >
                        <Target size={14} className="text-accent" />
                        {c.title}
                        <span className="ml-auto text-[11px] text-fg-3">zone {c.job_zone}</span>
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}

            {step === 4 && (
              <>
                <Field label={t("onb_hours")} hint={t("onb_hours_hint")}>
                  <input
                    type="range"
                    min={options?.hours_per_week_range[0] ?? 1}
                    max={options?.hours_per_week_range[1] ?? 40}
                    value={form.hours_per_week}
                    onChange={(e) => setForm({ ...form, hours_per_week: Number(e.target.value) })}
                    className="w-full accent-[var(--color-accent-primary)]"
                    aria-valuetext={`${form.hours_per_week} hours`}
                  />
                  <span className="text-sm text-accent">{form.hours_per_week} h / week</span>
                </Field>
                <Field label={t("language")} hint={t("onb_language_hint")}>
                  <select
                    className={inputCls}
                    value={form.language}
                    onChange={(e) => setForm({ ...form, language: e.target.value })}
                  >
                    {(options?.languages ?? ["en"]).map((l) => (
                      <option key={l} value={l}>
                        {l === "en" ? "English" : l === "ta" ? "தமிழ் (Tamil)" : "हिन्दी (Hindi)"}
                      </option>
                    ))}
                  </select>
                </Field>
                <div className="rounded-xl border border-white/10 bg-bg-3/40 p-3 text-sm text-fg-2">
                  <p className="flex items-center gap-2 text-fg">
                    <Compass size={15} className="text-accent" />
                    {t("onb_summary")}
                  </p>
                  <ul className="mt-2 space-y-1 text-xs">
                    <li>{t("onb_summary_persona")}: {form.persona || "—"}</li>
                    <li>{t("onb_summary_skills")}: {form.skills.length}</li>
                    <li>{t("onb_summary_target")}: {form.target || t("onb_summary_no_target")}</li>
                    <li>{t("onb_summary_hours")}: {form.hours_per_week} h/week</li>
                  </ul>
                </div>
              </>
            )}
          </motion.div>
        </AnimatePresence>

        {error && (
          <p role="alert" className="mt-3 text-xs text-danger">
            {error}
          </p>
        )}

        <div className="mt-5 flex items-center justify-between">
          <Button variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0}>
            <ArrowLeft size={15} /> {t("onb_back")}
          </Button>
          {step < STEPS.length - 1 ? (
            <Button onClick={() => setStep((s) => s + 1)} disabled={!canAdvance()}>
              {t("onb_next")} <ArrowRight size={15} />
            </Button>
          ) : (
            <Button onClick={submit} disabled={busy}>
              <Check size={15} /> {busy ? t("saving") : t("onb_finish")}
            </Button>
          )}
        </div>
      </Card>

      <SourceLabel text={t("onb_footer_source")} />
    </div>
  );
}
