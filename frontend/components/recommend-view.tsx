"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowUp, ChevronDown, FileText, Paperclip, Sparkles, Target, Wand2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useI18n } from "@/lib/i18n";
import type { ProfileInput, RecommendResponse } from "@/lib/types";
import { Disclosure, Magnetic, TextEffect } from "./motion";
import { ExecutionPanel, type Step } from "./execution-panel";
import { Results } from "./results";

const EXPERIENCE = ["Student / No experience", "Junior (0-2 years)", "Mid-level (2-5 years)", "Senior (5+ years)"];

const EXAMPLES = [
  { label: "Data analyst", skills: "Python, SQL, pandas, statistics, data visualization, Excel", goals: "Become a data analyst", interests: "AI, analytics" },
  { label: "Front-end", skills: "JavaScript, React, HTML, CSS, Git", goals: "Frontend developer", interests: "design, web" },
  { label: "Nursing", skills: "Patient care, first aid, biology, communication", goals: "Help people in a hospital", interests: "healthcare" },
  { label: "Accounts", skills: "Tally, accounting, Excel, GST filing", goals: "Accountant", interests: "finance" },
  { label: "Design", skills: "Photoshop, Illustrator, Figma, UI, UX", goals: "Designer", interests: "art, apps" },
];

const PLACEHOLDERS = [
  "Python, SQL, Excel, presenting to stakeholders…",
  "Tally, GST filing, bookkeeping, MS Office…",
  "Patient care, first aid, biology…",
  "AutoCAD, SolidWorks, thermodynamics…",
  "Teaching, English, Tamil, communication…",
];

export function RecommendView({
  interestsProfile,
  hollandCode,
  aiMode,
  onGoAssess,
}: {
  interestsProfile: Record<string, number> | null;
  hollandCode: string | null;
  aiMode: boolean;
  onGoAssess: () => void;
}) {
  const { t } = useI18n();
  const [skills, setSkills] = useState("");
  const [goals, setGoals] = useState("");
  const [interests, setInterests] = useState("");
  const [education, setEducation] = useState("");
  const [experience, setExperience] = useState(EXPERIENCE[0]);
  const [resume, setResume] = useState<{ name: string; text: string; skills: string[] } | null>(null);
  const [more, setMore] = useState(false);
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [steps, setSteps] = useState<Step[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RecommendResponse | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setInterval(() => setPlaceholderIdx((i) => (i + 1) % PLACEHOLDERS.length), 2600);
    return () => clearInterval(t);
  }, []);

  // Skill autocomplete for the last token
  useEffect(() => {
    const last = skills.split(/[,\n;]/).pop()?.trim() ?? "";
    if (last.length < 2) return setSuggestions([]);
    const h = setTimeout(() => api.suggestSkills(last).then((r) => setSuggestions(r.suggestions.filter((s) => s !== last.toLowerCase()).slice(0, 5))).catch(() => {}), 150);
    return () => clearTimeout(h);
  }, [skills]);

  const acceptSuggestion = (s: string) => {
    const parts = skills.split(/([,\n;])/);
    parts[parts.length - 1] = ` ${s}`;
    setSkills(parts.join("").replace(/^\s+/, "") + ", ");
    setSuggestions([]);
    areaRef.current?.focus();
  };

  const canSubmit = (skills.trim().length >= 3 || !!resume) && !running;

  const onFile = async (file: File) => {
    setError(null);
    setSteps([{ id: "resume", label: `Reading ${file.name}`, state: "active", icon: "document" }]);
    try {
      const r = await api.extractResume(file);
      setResume({ name: file.name, text: r.text, skills: r.skills });
      setSteps([{ id: "resume", label: `Extracted ${r.characters.toLocaleString()} characters · ${r.skills.length} skills found`, state: "complete", icon: "document" }]);
    } catch (e) {
      setSteps([]);
      setError((e as Error).message);
    }
  };

  const run = useCallback(async () => {
    if (!canSubmit) return;
    setError(null);
    setResult(null);
    setRunning(true);
    const plan: Step[] = [
      { id: "parse", label: t("step_parse"), state: "active", icon: "search" },
      { id: "match", label: t("step_match"), state: "pending", icon: "globe" },
      { id: "gaps", label: t("step_gaps"), state: "pending", icon: "eye" },
      { id: "market", label: t("step_market"), state: "pending", icon: "pencil" },
      ...(aiMode ? [{ id: "llm", label: t("step_llm"), state: "pending" as const, icon: "sparkles" as const }] : []),
    ];
    setSteps(plan);
    const advance = (i: number) =>
      setSteps((s) => s.map((st, idx) => ({ ...st, state: idx < i ? "complete" : idx === i ? "active" : "pending" })));
    const timers = [setTimeout(() => advance(1), 350), setTimeout(() => advance(2), 800), setTimeout(() => advance(3), 1200), setTimeout(() => advance(4), 1700)];
    const body: ProfileInput = {
      skills,
      goals,
      interests,
      education,
      experience_level: experience,
      resume_text: resume?.text ?? "",
      interests_profile: interestsProfile,
    };
    try {
      const r = await api.recommend(body);
      timers.forEach(clearTimeout);
      setSteps((s) => s.map((st) => ({ ...st, state: "complete" })));
      setResult(r);
      setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 250);
    } catch (e) {
      timers.forEach(clearTimeout);
      setSteps((s) => s.map((st) => (st.state === "active" ? { ...st, state: "error" } : st)));
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }, [canSubmit, skills, goals, interests, education, experience, resume, interestsProfile, aiMode, t]);

  const onKey = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") run();
  };

  const detected = useMemo(() => result?.detected_skills ?? [], [result]);

  return (
    <div className="flex flex-col gap-8">
      {/* Hero */}
      <header className="pt-6 text-center sm:pt-12">
        <TextEffect as="h1" className="font-serif text-4xl leading-[1.1] tracking-tight sm:text-[52px]" per="word" key={t("hero_title")}>
          {t("hero_title")}
        </TextEffect>
        <motion.p initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5, duration: 0.5 }} className="mx-auto mt-4 max-w-xl text-[15px] text-fg-2">
          {t("hero_sub")}
        </motion.p>
      </header>

      {/* Composer */}
      <motion.section
        initial={{ opacity: 0, y: 16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ delay: 0.35, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className={cn("relative rounded-[20px] bg-bg-3 p-3 shadow-[var(--shadow-md)] ring-1 ring-white/5 transition", running && "border-trail")}
      >
        <label htmlFor="skills" className="sr-only">
          {t("skills_label")}
        </label>
        <textarea
          id="skills"
          ref={areaRef}
          value={skills}
          onChange={(e) => setSkills(e.target.value)}
          onKeyDown={onKey}
          rows={3}
          placeholder={PLACEHOLDERS[placeholderIdx]}
          className="min-h-[88px] w-full resize-none bg-transparent px-2 pt-1 text-[15px] leading-relaxed text-fg placeholder:text-fg-3 focus:outline-none"
        />

        {/* Autocomplete */}
        <AnimatePresence>
          {suggestions.length > 0 && (
            <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} className="flex flex-wrap gap-1.5 px-2 pb-2">
              {suggestions.map((s) => (
                <button key={s} onClick={() => acceptSuggestion(s)} className="rounded-full bg-bg-4 px-2.5 py-1 text-xs text-fg-2 transition hover:bg-accent/20 hover:text-accent">
                  + {s}
                </button>
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Attachments */}
        <AnimatePresence>
          {resume && (
            <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="px-2 pb-2">
              <div className="inline-flex items-center gap-2 rounded-[var(--radius-md)] bg-bg-4 px-3 py-2 text-xs">
                <FileText size={14} className="text-accent" />
                <span className="max-w-[200px] truncate">{resume.name}</span>
                <span className="text-fg-3">· {resume.skills.length} skills</span>
                <button onClick={() => setResume(null)} aria-label={t("remove_resume")} className="ml-1 text-fg-3 hover:text-fg">
                  <X size={14} />
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <Disclosure open={more}>
          <div className="grid gap-2 px-2 pb-3 pt-1 sm:grid-cols-2">
            <Field label={t("goal")} value={goals} onChange={setGoals} placeholder={t("goal_ph")} />
            <Field label={t("interests")} value={interests} onChange={setInterests} placeholder={t("interests_ph")} />
            <Field label={t("education")} value={education} onChange={setEducation} placeholder={t("education_ph")} />
            <label className="flex flex-col gap-1 text-xs text-fg-2">
              Experience
              <select value={experience} onChange={(e) => setExperience(e.target.value)} className="rounded-[var(--radius-sm)] bg-bg-4 px-3 py-2 text-sm text-fg focus:outline-none focus:ring-1 focus:ring-accent">
                {EXPERIENCE.map((x) => (
                  <option key={x}>{x}</option>
                ))}
              </select>
            </label>
          </div>
        </Disclosure>

        <div className="flex items-center justify-between gap-2 border-t border-white/5 px-1 pt-2">
          <div className="flex items-center gap-1">
            <input ref={fileRef} type="file" accept=".txt,.md,.pdf" className="hidden" onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} />
            <IconBtn label={t("attach_resume")} onClick={() => fileRef.current?.click()}>
              <Paperclip size={16} />
            </IconBtn>
            <button onClick={() => setMore((m) => !m)} className={cn("flex items-center gap-1 rounded-full px-3 py-1.5 text-xs transition", more ? "bg-accent/15 text-accent" : "text-fg-2 hover:bg-bg-4 hover:text-fg")}>
              {t("details")} <ChevronDown size={14} className={cn("transition-transform", more && "rotate-180")} />
            </button>
            <button onClick={onGoAssess} className={cn("hidden items-center gap-1 rounded-full px-3 py-1.5 text-xs transition sm:flex", hollandCode ? "bg-accent/15 text-accent" : "text-fg-2 hover:bg-bg-4 hover:text-fg")}>
              <Target size={14} /> {hollandCode ? `Interests ${hollandCode}` : t("quiz_cta")}
            </button>
          </div>
          <div className="flex items-center gap-2">
            <span className="hidden text-[11px] text-fg-3 sm:inline">⌘/Ctrl + Enter</span>
            <Magnetic strength={0.25}>
              <button
                onClick={run}
                disabled={!canSubmit}
                aria-label={t("submit")}
                className={cn(
                  "grid h-10 w-10 place-items-center rounded-full transition-all duration-200",
                  canSubmit ? "bg-accent text-black shadow-[0_0_24px_rgba(0,212,170,0.35)] hover:scale-105" : "bg-bg-4 text-fg-3",
                )}
              >
                {running ? <span className="h-4 w-4 rounded-full border-2 border-black/30 border-t-black loading-ring" /> : <ArrowUp size={18} />}
              </button>
            </Magnetic>
          </div>
        </div>
      </motion.section>

      {/* Quick examples */}
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.6 }} className="-mt-4 flex flex-wrap items-center justify-center gap-2">
        <span className="text-xs text-fg-3">{t("try")}</span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex.label}
            onClick={() => {
              setSkills(ex.skills);
              setGoals(ex.goals);
              setInterests(ex.interests);
              areaRef.current?.focus();
            }}
            className="rounded-full border border-white/10 px-3 py-1 text-xs text-fg-2 transition hover:border-accent/40 hover:bg-accent/10 hover:text-accent"
          >
            <Wand2 size={11} className="mr-1 inline" />
            {ex.label}
          </button>
        ))}
      </motion.div>

      <AnimatePresence>{steps.length > 0 && <ExecutionPanel steps={steps} onDismiss={() => !running && setSteps([])} />}</AnimatePresence>

      <AnimatePresence>
        {error && (
          <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} role="alert" className="rounded-[var(--radius-md)] border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-[#ff9b9b]">
            {error}
          </motion.div>
        )}
      </AnimatePresence>

      <div ref={resultsRef}>
        {result && (
          <Results
            result={result}
            detected={detected}
            onRefine={(s) => {
              setSkills((cur) => (cur.trim() ? `${cur.trim().replace(/,$/, "")}, ${s}` : s));
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
          />
        )}
      </div>

      {!result && steps.length === 0 && (
        <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 1 }} className="text-center text-xs text-fg-3">
          <Sparkles size={12} className="mr-1 inline text-accent" />
          Grounded in the O*NET taxonomy · Resumes are processed in memory · Nothing leaves your server in offline mode
        </motion.p>
      )}
    </div>
  );
}

function Field({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-fg-2">
      {label}
      <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="rounded-[var(--radius-sm)] bg-bg-4 px-3 py-2 text-sm text-fg placeholder:text-fg-3 focus:outline-none focus:ring-1 focus:ring-accent" />
    </label>
  );
}

function IconBtn({ children, label, onClick }: { children: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} aria-label={label} title={label} className="grid h-9 w-9 place-items-center rounded-full text-fg-2 transition hover:bg-bg-4 hover:text-fg">
      {children}
    </button>
  );
}
