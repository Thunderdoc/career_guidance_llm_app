"use client";

/**
 * Public landing page (sell-standard, Phase 1 consolidated).
 *
 * Order (docs/UPGRADE_PLAN.md Phase 1.3): hero → live try-it → sample
 * report → 3 differentiators → trust strip → how it works (4 steps) →
 * pricing (Individuals / Institutions + demo form) → FAQ → footer.
 * Honesty rules: the hero carries NO numeric statistic beyond the
 * verifiable "974 occupations" from docs/SOURCES.md entry #1; features
 * that are not built yet are labelled "Coming soon" with their phase;
 * pricing comes from /api/v1/billing/plans ("Contact us" when unset);
 * no testimonials, no user counts, no stock photos of people.
 */
import { motion } from "motion/react";
import { ArrowRight, BadgeCheck, CalendarRange, Check, Compass, FileText, Languages, Route, Search, ShieldCheck, Sparkles, Target } from "lucide-react";
import { useEffect, useState } from "react";
import { api, billingApi, type BillingPlan } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Recommendation } from "@/lib/types";
import { Badge } from "./ui/badge";
import { ScoreMeter } from "./ui/score-meter";
import { SourceLabel } from "./ui/source-label";
import { Tabs } from "./ui/tabs";
import { ErrorNote, Spinner } from "./ui";

const FEATURES = [
  {
    icon: <Compass size={22} />,
    title: "Skill matching",
    body: "Your skills matched against 974 occupations, with the gaps spelled out — what you have, what you are missing.",
  },
  {
    icon: <Target size={22} />,
    title: "Interest assessment",
    body: "A short RIASEC quiz that turns your interests into a profile and narrows the field to careers that fit.",
  },
  {
    icon: <Route size={22} />,
    title: "Learning roadmaps",
    body: "Week-by-week plans with resources, so a recommendation becomes something you can actually follow.",
  },
  {
    icon: <FileText size={22} />,
    title: "Job-fit check",
    body: "Paste a job description and your résumé to see where you stand before you apply.",
  },
];

const DIFFERENTIATORS = [
  {
    icon: <Sparkles size={22} />,
    title: "India Reality Score",
    body: "How realistic and in-demand a career is for a fresher in India right now — demand, salary ladder, barrier to entry, shown component by component with sources.",
    status: "Coming soon — Phase 2",
  },
  {
    icon: <BadgeCheck size={22} />,
    title: "Proof of skill",
    body: "Verified skills, not just claimed skills: short auto-graded quizzes and reviewed project evidence on an opt-in public profile.",
    status: "Coming soon — Phase 3",
  },
  {
    icon: <CalendarRange size={22} />,
    title: "90-day plan",
    body: "A week-by-week plan built from your available hours and budget, with checks that move skills toward verified — not a one-time list.",
    status: "Coming soon — Phase 3",
  },
];

const STEPS = [
  { n: "1", title: "Tell us who you are", body: "Student, fresher or switcher — plus your skills and interests." },
  { n: "2", title: "Add your constraints", body: "City, hours a week, budget and goal, so the plan fits your life." },
  { n: "3", title: "Get your career report", body: "Top-5 careers with match scores, gaps and what to learn first." },
  { n: "4", title: "Follow your plan", body: "Sign in to save it, track progress and export your roadmap." },
];

const FAQS = [
  {
    q: "Where does the career data come from?",
    a: "A catalogue of 974 occupations from O*NET (U.S. Department of Labor, CC BY 4.0) with skills, tasks and requirements, plus curated market data for India. AI features are optional, labelled, and never presented as facts.",
  },
  {
    q: "Do I need an account?",
    a: "No — you can complete the wizard and see your first career report without signing in. Sign-in is asked only when you want to save, export, see the full plan or verify skills.",
  },
  {
    q: "Which languages are supported?",
    a: "The app works in English, Tamil and Hindi.",
  },
  {
    q: "Is my data private?",
    a: "Your runs, plans and progress belong to your account only. Anonymous first runs are not attached to any account. You can export everything or delete your account from Settings.",
  },
];

/** Sample report card: the real card layout rendered with demo data. */
const SAMPLE_REC: Partial<Recommendation> = {
  title: "Data Analysts (sample)",
  match_percent: 78,
  matching_skills: ["python", "sql", "excel"],
  missing_skills: ["statistics", "tableau"],
  suitability: "intermediate",
};

function SampleReport() {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6" aria-label="Sample career report">
      <div className="flex items-center justify-between">
        <h3 className="font-serif text-xl">{SAMPLE_REC.title}</h3>
        <Badge>Sample</Badge>
      </div>
      <div className="mt-4 max-w-xs">
        <ScoreMeter value={SAMPLE_REC.match_percent ?? 0} label="Match score" />
      </div>
      <div className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
        <div><h4 className="font-medium">You already have</h4><p className="mt-1 text-fg-2">{SAMPLE_REC.matching_skills?.join(", ")}</p></div>
        <div><h4 className="font-medium">Learn these first</h4><p className="mt-1 text-fg-2">{SAMPLE_REC.missing_skills?.join(", ")}</p></div>
      </div>
      <SourceLabel source="Sample data for illustration — your report uses your own skills and the O*NET catalogue" />
    </div>
  );
}

function TryIt() {
  const { t } = useI18n();
  const [skills, setSkills] = useState("");
  const [rec, setRec] = useState<Recommendation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = async () => {
    setBusy(true); setError(""); setRec(null);
    try {
      const res = await api.recommend({
        skills, interests: "", education: "", experience_level: "Student / No experience",
        goals: "", resume_text: "",
      });
      const top = res.recommendations[0] ?? null;
      setRec(top);
      if (top && res.run_id) {
        try { window.sessionStorage.setItem(`cg.report.${res.run_id}`, JSON.stringify(res)); } catch { /* private mode */ }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong. Please try again.");
    } finally { setBusy(false); }
  };

  return (
    <div className="rounded-2xl border border-accent/30 bg-white/[0.03] p-6">
      <h2 className="font-serif text-2xl">{t("p1_try_title")}</h2>
      <div className="mt-4 flex flex-col gap-3 sm:flex-row">
        <label className="sr-only" htmlFor="try-skills">{t("skills_label")}</label>
        <input id="try-skills" value={skills} onChange={(e) => setSkills(e.target.value)} placeholder={t("p1_try_ph")}
          className="min-h-[44px] flex-1 rounded-xl border border-white/15 bg-transparent px-4 py-3 text-sm outline-none focus:border-accent/60" />
        <button type="button" disabled={busy || skills.trim().length < 3} onClick={() => void run()}
          className="flex min-h-[44px] items-center justify-center gap-2 rounded-xl bg-white px-5 py-3 text-sm font-medium text-black transition hover:bg-white/90 disabled:opacity-40">
          {t("p1_try_button")} <ArrowRight size={16} />
        </button>
      </div>
      <div className="mt-3"><ErrorNote error={error} /></div>
      {busy && <Spinner label="Matching…" />}
      {rec && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mt-4 rounded-xl border border-white/10 bg-black/20 p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-serif text-xl">{rec.title}</h3>
          </div>
          <div className="mt-3 max-w-xs"><ScoreMeter value={rec.match_percent ?? Math.round(rec.match_score * 100)} label="Match score" /></div>
          <p className="mt-3 text-sm text-fg-2">{rec.match_reason}</p>
          <p className="mt-2 text-sm"><span className="text-fg-2">Learn first:</span> {rec.missing_skills.slice(0, 3).join(", ") || "—"}</p>
          <a href="/start" className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-accent">Get the full report <ArrowRight size={15} /></a>
        </motion.div>
      )}
    </div>
  );
}

function priceLabel(plan: BillingPlan): string {
  if (plan.price_inr === 0) return "Free";
  if (plan.price_inr === null) return "Contact us";
  return `₹${plan.price_inr}/month`;
}

function DemoForm() {
  const [form, setForm] = useState({ name: "", email: "", organisation: "", seats: "", message: "" });
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setError("");
    try {
      await billingApi.demoRequest({
        name: form.name, email: form.email, organisation: form.organisation,
        seats: form.seats ? Number(form.seats) : null, message: form.message,
      });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the request.");
    } finally { setBusy(false); }
  };

  if (done) {
    return <p className="rounded-xl border border-white/10 bg-white/[0.02] p-5 text-sm">Thanks — your demo request is saved. We will reply to {form.email}. (No e-mail is sent automatically; this is stored for the team.)</p>;
  }
  const inputCls = "min-h-[44px] w-full rounded-xl border border-white/15 bg-transparent px-4 py-3 text-sm outline-none focus:border-accent/60";
  return (
    <form onSubmit={(e) => void submit(e)} className="grid gap-3 rounded-2xl border border-white/10 bg-white/[0.02] p-6 sm:grid-cols-2">
      <div><label htmlFor="demo-name" className="text-sm text-fg-2">Your name</label><input id="demo-name" required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={`mt-1 ${inputCls}`} /></div>
      <div><label htmlFor="demo-email" className="text-sm text-fg-2">Work e-mail</label><input id="demo-email" required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className={`mt-1 ${inputCls}`} /></div>
      <div><label htmlFor="demo-org" className="text-sm text-fg-2">Institute / organisation</label><input id="demo-org" required minLength={2} value={form.organisation} onChange={(e) => setForm({ ...form, organisation: e.target.value })} className={`mt-1 ${inputCls}`} /></div>
      <div><label htmlFor="demo-seats" className="text-sm text-fg-2">Seats needed (optional)</label><input id="demo-seats" type="number" min={1} value={form.seats} onChange={(e) => setForm({ ...form, seats: e.target.value })} className={`mt-1 ${inputCls}`} /></div>
      <div className="sm:col-span-2"><label htmlFor="demo-msg" className="text-sm text-fg-2">Message (optional)</label><textarea id="demo-msg" value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} className={`mt-1 ${inputCls}`} rows={3} /></div>
      <div className="sm:col-span-2"><ErrorNote error={error} /></div>
      <button type="submit" disabled={busy} className="min-h-[44px] rounded-xl bg-white px-5 py-3 text-sm font-medium text-black transition hover:bg-white/90 disabled:opacity-40 sm:col-span-2">
        {busy ? "Sending…" : "Request a demo"}
      </button>
    </form>
  );
}

function Pricing() {
  const [plans, setPlans] = useState<BillingPlan[] | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("individuals");

  const load = () => {
    setError("");
    billingApi.plans().then((res) => setPlans(res.plans))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load pricing."));
  };
  useEffect(load, []);

  if (error) return <ErrorNote error={error} retry={load} />;
  if (!plans) return <Spinner label="Loading pricing…" />;
  const shown = tab === "individuals" ? plans.filter((p) => p.id !== "institute") : plans.filter((p) => p.id === "institute");

  return (
    <div>
      <div className="mb-6 flex justify-center">
        <Tabs tabs={[{ id: "individuals", label: "Individuals" }, { id: "institutions", label: "Institutions" }]} active={tab} onChange={setTab} />
      </div>
      <div className={`grid gap-4 ${shown.length > 1 ? "md:grid-cols-2" : "mx-auto max-w-md"}`}>
        {shown.map((plan) => (
          <div key={plan.id} className={`rounded-2xl border p-6 ${plan.id === "pro" ? "border-accent/60 bg-white/[0.04]" : "border-white/10 bg-white/[0.02]"}`}>
            <h3 className="font-serif text-2xl">{plan.name}</h3>
            <p className="mt-1 text-sm text-fg-2">{plan.tagline}</p>
            <p className="mt-4 text-3xl font-semibold">{priceLabel(plan)}</p>
            {plan.id === "pro" && plan.trial_days > 0 && <p className="mt-1 text-sm text-accent">Includes a {plan.trial_days}-day free trial.</p>}
            <ul className="mt-5 space-y-2">
              {plan.features.map((feature) => (
                <li key={feature} className="flex gap-2 text-sm text-fg-2"><Check size={16} className="mt-0.5 shrink-0 text-accent" /><span>{feature}</span></li>
              ))}
            </ul>
            <a href="/start" className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-white px-4 py-3 text-sm font-medium text-black transition hover:bg-white/90">
              Get started <ArrowRight size={16} />
            </a>
          </div>
        ))}
      </div>
      {tab === "institutions" && <div className="mx-auto mt-6 max-w-xl"><DemoForm /></div>}
    </div>
  );
}

export function LandingView() {
  const { t } = useI18n();
  return (
    <main className="mx-auto w-full max-w-5xl px-5 pb-20">
      <header className="flex items-center justify-between py-6">
        <span className="font-serif text-xl">Career Guidance AI</span>
        <a href="/login" className="rounded-xl border border-white/15 px-4 py-2 text-sm font-medium transition hover:bg-white/5">Sign in</a>
      </header>

      <motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="pt-10 text-center md:pt-16">
        <h1 className="mx-auto max-w-2xl font-serif text-4xl leading-tight md:text-5xl">
          Find a career that fits your skills — honestly, for India.
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-base text-fg-2">
          Your Top-5 careers from 974 real occupations (O*NET), with the skills you have,
          the gaps to close, and what to learn first. No sign-in needed for your first report.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <a href="/start" className="flex min-h-[44px] items-center gap-2 rounded-xl bg-white px-6 py-3 text-sm font-medium text-black transition hover:bg-white/90">
            Get my career report <ArrowRight size={16} />
          </a>
          <a href="#sample" className="min-h-[44px] rounded-xl border border-white/15 px-6 py-3 text-sm font-medium transition hover:bg-white/5">See a sample report</a>
        </div>
        <p className="mt-4 flex items-center justify-center gap-2 text-sm text-fg-2">
          <Languages size={15} /> English · Tamil · Hindi <span aria-hidden>·</span> <Search size={15} /> Career search is free, no account needed
        </p>
        <SourceLabel source="Occupation catalogue: O*NET, U.S. Department of Labor (CC BY 4.0) — see docs/SOURCES.md" asOf="2026-11-06" />
      </motion.section>

      <section className="mt-14"><TryIt /></section>

      <section id="sample" className="mt-14 scroll-mt-8">
        <h2 className="mb-6 text-center font-serif text-3xl">What your report looks like</h2>
        <div className="mx-auto max-w-2xl"><SampleReport /></div>
      </section>

      <section className="mt-16 grid gap-4 md:mt-20 md:grid-cols-2">
        {FEATURES.map((feature) => (
          <div key={feature.title} className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
            <div className="text-accent">{feature.icon}</div>
            <h2 className="mt-3 font-serif text-xl">{feature.title}</h2>
            <p className="mt-1 text-sm text-fg-2">{feature.body}</p>
          </div>
        ))}
      </section>

      <section className="mt-16 md:mt-20">
        <h2 className="text-center font-serif text-3xl">What makes this different</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {DIFFERENTIATORS.map((d) => (
            <div key={d.title} className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
              <div className="flex items-center justify-between">
                <div className="text-accent">{d.icon}</div>
                <Badge>{t("p1_coming_soon")}</Badge>
              </div>
              <h3 className="mt-3 font-serif text-xl">{d.title}</h3>
              <p className="mt-1 text-sm text-fg-2">{d.body}</p>
              <p className="mt-3 text-xs text-fg-3">{d.status}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-16 rounded-2xl border border-white/10 bg-white/[0.02] p-6 md:mt-20">
        <h2 className="flex items-center gap-2 font-serif text-2xl"><ShieldCheck className="text-accent" size={22} /> Built on sources, not guesses</h2>
        <ul className="mt-4 grid gap-3 text-sm text-fg-2 md:grid-cols-3">
          <li>Career data: O*NET occupational catalogue (974 occupations), U.S. Department of Labor, CC BY 4.0.</li>
          <li>Every salary or demand figure in a report carries its source label; estimates are labelled as estimates.</li>
          <li>Privacy: anonymous first runs attach to no account; under-18 protections and parental consent are on the roadmap (Phase 5).</li>
        </ul>
      </section>

      <section className="mt-16 md:mt-20">
        <h2 className="text-center font-serif text-3xl">How it works</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-4">
          {STEPS.map((step) => (
            <div key={step.n} className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
              <span className="font-serif text-3xl text-accent">{step.n}</span>
              <h3 className="mt-2 font-serif text-xl">{step.title}</h3>
              <p className="mt-1 text-sm text-fg-2">{step.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="pricing" className="mt-16 scroll-mt-8 md:mt-20">
        <h2 className="text-center font-serif text-3xl">Pricing</h2>
        <p className="mt-2 text-center text-sm text-fg-2">Start free. Upgrade when you want the full toolkit.</p>
        <div className="mt-8"><Pricing /></div>
      </section>

      <section className="mt-16 md:mt-20">
        <h2 className="text-center font-serif text-3xl">Questions</h2>
        <div className="mx-auto mt-8 max-w-2xl space-y-4">
          {FAQS.map((faq) => (
            <div key={faq.q} className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
              <h3 className="font-serif text-lg">{faq.q}</h3>
              <p className="mt-1 text-sm text-fg-2">{faq.a}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="mt-16 flex flex-col items-center gap-3 border-t border-white/10 pt-8 text-sm text-fg-2 md:mt-20">
        <span className="font-serif text-base text-white">Career Guidance AI</span>
        <div className="flex gap-5">
          <a href="/terms" className="hover:text-white">Terms</a>
          <a href="/privacy" className="hover:text-white">Privacy</a>
          <a href="/refund" className="hover:text-white">Refunds</a>
        </div>
        <p className="max-w-xl text-center text-xs text-fg-3">
          O*NET® is a trademark of the U.S. Department of Labor, Employment and Training Administration; catalogue content used under CC BY 4.0.
        </p>
      </footer>
    </main>
  );
}
