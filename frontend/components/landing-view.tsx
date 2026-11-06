"use client";

/**
 * Public landing page (sell-standard, Phase 1 consolidated).
 *
 * Order (docs/UPGRADE_PLAN.md Phase 1.3): hero → live try-it → sample
 * report → 3 differentiators → trust strip → how it works (4 steps) →
 * pricing (Individuals / Institutions + demo form) → FAQ → footer.
 * Honesty rules: the hero carries NO numeric statistic beyond the
 * verifiable "974 occupations" from docs/SOURCES.md entry #1; the three
 * differentiators shown are shipped features (Phases 2–3) — anything not
 * built yet is labelled "Coming soon" with its phase; pricing comes from
 * /api/v1/billing/plans ("Contact us" when unset); no testimonials, no
 * user counts, no stock photos of people. All chrome copy is localised
 * via p6_* i18n keys (EN/TA/HI); plan names/features come from the API.
 */
import { motion } from "motion/react";
import { ArrowRight, BadgeCheck, CalendarRange, Check, Compass, FileText, Languages, Route, Search, ShieldCheck, Sparkles, Target } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, billingApi, type BillingPlan } from "@/lib/api";
import { BandwidthToggle } from "./bandwidth-toggle";
import { LOCALES, useI18n, type Key } from "@/lib/i18n";
import type { Recommendation } from "@/lib/types";
import { Badge } from "./ui/badge";
import { ScoreMeter } from "./ui/score-meter";
import { SourceLabel } from "./ui/source-label";
import { Tabs } from "./ui/tabs";
import { ErrorNote, Spinner } from "./ui";

/* Copy lives in the i18n dictionaries (p6_* keys, EN/TA/HI) so the whole
 * landing switches with the language switcher (Phase 6). Career content
 * itself (O*NET titles/skills) stays English, per the i18n convention. */
const FEATURES = [
  { icon: <Compass size={22} />, titleKey: "p6_feat1_t", bodyKey: "p6_feat1_b" },
  { icon: <Target size={22} />, titleKey: "p6_feat2_t", bodyKey: "p6_feat2_b" },
  { icon: <Route size={22} />, titleKey: "p6_feat3_t", bodyKey: "p6_feat3_b" },
  { icon: <FileText size={22} />, titleKey: "p6_feat4_t", bodyKey: "p6_feat4_b" },
] as const;

const DIFFERENTIATORS = [
  { icon: <Sparkles size={22} />, titleKey: "p6_diff1_t", bodyKey: "p6_diff1_b" },
  { icon: <BadgeCheck size={22} />, titleKey: "p6_diff2_t", bodyKey: "p6_diff2_b" },
  { icon: <CalendarRange size={22} />, titleKey: "p6_diff3_t", bodyKey: "p6_diff3_b" },
] as const;

const STEPS = [
  { n: "1", titleKey: "p6_step1_t", bodyKey: "p6_step1_b" },
  { n: "2", titleKey: "p6_step2_t", bodyKey: "p6_step2_b" },
  { n: "3", titleKey: "p6_step3_t", bodyKey: "p6_step3_b" },
  { n: "4", titleKey: "p6_step4_t", bodyKey: "p6_step4_b" },
] as const;

const FAQS = [
  { qKey: "p6_faq1_q", aKey: "p6_faq1_a" },
  { qKey: "p6_faq2_q", aKey: "p6_faq2_a" },
  { qKey: "p6_faq3_q", aKey: "p6_faq3_a" },
  { qKey: "p6_faq4_q", aKey: "p6_faq4_a" },
] as const;

/** Sample report card: the real card layout rendered with demo data. */
const SAMPLE_REC: Partial<Recommendation> = {
  // Career titles stay English (i18n convention); the "(sample)" marker is
  // the localised badge next to the title, not part of the title itself.
  title: "Data Analysts",
  match_percent: 78,
  matching_skills: ["python", "sql", "excel"],
  missing_skills: ["statistics", "tableau"],
  suitability: "intermediate",
};

function SampleReport() {
  const { t } = useI18n();
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-6" aria-label={t("p6_sample_heading")}>
      <div className="flex items-center justify-between">
        <h3 className="font-serif text-xl">{SAMPLE_REC.title}</h3>
        <Badge>{t("p6_sample_badge")}</Badge>
      </div>
      <div className="mt-4 max-w-xs">
        <ScoreMeter value={SAMPLE_REC.match_percent ?? 0} label={t("p6_match_score")} />
      </div>
      <div className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
        <div><h4 className="font-medium">{t("p6_you_have")}</h4><p className="mt-1 text-fg-2">{SAMPLE_REC.matching_skills?.join(", ")}</p></div>
        <div><h4 className="font-medium">{t("p6_learn_first")}</h4><p className="mt-1 text-fg-2">{SAMPLE_REC.missing_skills?.join(", ")}</p></div>
      </div>
      <SourceLabel source={t("p6_sample_source")} />
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
      setError(e instanceof Error ? e.message : t("error_generic"));
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
      {busy && <Spinner label={t("p6_matching")} />}
      {rec && (
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="mt-4 rounded-xl border border-white/10 bg-black/20 p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-serif text-xl">{rec.title}</h3>
          </div>
          <div className="mt-3 max-w-xs"><ScoreMeter value={rec.match_percent ?? Math.round(rec.match_score * 100)} label={t("p6_match_score")} /></div>
          <p className="mt-3 text-sm text-fg-2">{rec.match_reason}</p>
          <p className="mt-2 text-sm"><span className="text-fg-2">{t("p6_learn_first_short")}</span> {rec.missing_skills.slice(0, 3).join(", ") || "—"}</p>
          <a href="/start" className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-accent">{t("p6_full_report")} <ArrowRight size={15} /></a>
        </motion.div>
      )}
    </div>
  );
}

type Translate = (key: Key, vars?: Record<string, string | number>) => string;

function priceLabel(plan: BillingPlan, t: Translate): string {
  if (plan.price_inr === 0) return t("p6_free");
  if (plan.price_inr === null) return t("p6_contact_us");
  return t("p6_price_month", { n: plan.price_inr });
}

function DemoForm() {
  const { t } = useI18n();
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
      setError(err instanceof Error ? err.message : t("p6_demo_error"));
    } finally { setBusy(false); }
  };

  if (done) {
    return <p className="rounded-xl border border-white/10 bg-white/[0.02] p-5 text-sm">{t("p6_demo_done", { email: form.email })}</p>;
  }
  const inputCls = "min-h-[44px] w-full rounded-xl border border-white/15 bg-transparent px-4 py-3 text-sm outline-none focus:border-accent/60";
  return (
    <form onSubmit={(e) => void submit(e)} className="grid gap-3 rounded-2xl border border-white/10 bg-white/[0.02] p-6 sm:grid-cols-2">
      <div><label htmlFor="demo-name" className="text-sm text-fg-2">{t("p6_demo_name")}</label><input id="demo-name" required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={`mt-1 ${inputCls}`} /></div>
      <div><label htmlFor="demo-email" className="text-sm text-fg-2">{t("p6_demo_email")}</label><input id="demo-email" required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className={`mt-1 ${inputCls}`} /></div>
      <div><label htmlFor="demo-org" className="text-sm text-fg-2">{t("p6_demo_org")}</label><input id="demo-org" required minLength={2} value={form.organisation} onChange={(e) => setForm({ ...form, organisation: e.target.value })} className={`mt-1 ${inputCls}`} /></div>
      <div><label htmlFor="demo-seats" className="text-sm text-fg-2">{t("p6_demo_seats")}</label><input id="demo-seats" type="number" min={1} value={form.seats} onChange={(e) => setForm({ ...form, seats: e.target.value })} className={`mt-1 ${inputCls}`} /></div>
      <div className="sm:col-span-2"><label htmlFor="demo-msg" className="text-sm text-fg-2">{t("p6_demo_msg")}</label><textarea id="demo-msg" value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} className={`mt-1 ${inputCls}`} rows={3} /></div>
      <div className="sm:col-span-2"><ErrorNote error={error} /></div>
      <button type="submit" disabled={busy} className="min-h-[44px] rounded-xl bg-white px-5 py-3 text-sm font-medium text-black transition hover:bg-white/90 disabled:opacity-40 sm:col-span-2">
        {busy ? t("p6_demo_sending") : t("p6_demo_submit")}
      </button>
    </form>
  );
}

function Pricing() {
  const { t } = useI18n();
  const [plans, setPlans] = useState<BillingPlan[] | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("individuals");

  const load = useCallback(() => {
    setError("");
    billingApi.plans().then((res) => setPlans(res.plans))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : t("error_generic")));
  }, [t]);
  useEffect(() => { load(); }, [load]);

  if (error) return <ErrorNote error={error} retry={load} />;
  if (!plans) return <Spinner label={t("p6_loading_pricing")} />;
  const shown = tab === "individuals" ? plans.filter((p) => p.id !== "institute") : plans.filter((p) => p.id === "institute");

  return (
    <div>
      <div className="mb-6 flex justify-center">
        <Tabs tabs={[{ id: "individuals", label: t("p6_tab_individuals") }, { id: "institutions", label: t("p6_tab_institutions") }]} active={tab} onChange={setTab} />
      </div>
      <div className={`grid gap-4 ${shown.length > 1 ? "md:grid-cols-2" : "mx-auto max-w-md"}`}>
        {shown.map((plan) => (
          <div key={plan.id} className={`rounded-2xl border p-6 ${plan.id === "pro" ? "border-accent/60 bg-white/[0.04]" : "border-white/10 bg-white/[0.02]"}`}>
            <h3 className="font-serif text-2xl">{plan.name}</h3>
            <p className="mt-1 text-sm text-fg-2">{plan.tagline}</p>
            <p className="mt-4 text-3xl font-semibold">{priceLabel(plan, t)}</p>
            {plan.id === "pro" && plan.trial_days > 0 && <p className="mt-1 text-sm text-accent">{t("p6_trial", { n: plan.trial_days })}</p>}
            <ul className="mt-5 space-y-2">
              {plan.features.map((feature) => (
                <li key={feature} className="flex gap-2 text-sm text-fg-2"><Check size={16} className="mt-0.5 shrink-0 text-accent" /><span>{feature}</span></li>
              ))}
            </ul>
            <a href="/start" className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-white px-4 py-3 text-sm font-medium text-black transition hover:bg-white/90">
              {t("p6_get_started")} <ArrowRight size={16} />
            </a>
          </div>
        ))}
      </div>
      {tab === "institutions" && <div className="mx-auto mt-6 max-w-xl"><DemoForm /></div>}
    </div>
  );
}

export function LandingView() {
  const { t, locale, setLocale } = useI18n();
  return (
    <main className="mx-auto w-full max-w-5xl px-5 pb-20">
      <header className="flex items-center justify-between py-6">
        <span className="font-serif text-xl">Career Guidance AI</span>
        <div className="flex items-center gap-2">
          <BandwidthToggle variant="compact" />
          <a href="/login" className="rounded-xl border border-white/15 px-4 py-2 text-sm font-medium transition hover:bg-white/5">{t("sign_in")}</a>
        </div>
      </header>

      <motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="pt-10 text-center md:pt-16">
        <h1 className="mx-auto max-w-2xl font-serif text-4xl leading-tight md:text-5xl">
          {t("p6_hero_title")}
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-base text-fg-2">
          {t("p6_hero_sub")}
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <a href="/start" className="flex min-h-[44px] items-center gap-2 rounded-xl bg-white px-6 py-3 text-sm font-medium text-black transition hover:bg-white/90">
            {t("p1_start_title")} <ArrowRight size={16} />
          </a>
          <a href="#sample" className="min-h-[44px] rounded-xl border border-white/15 px-6 py-3 text-sm font-medium transition hover:bg-white/5">{t("p6_cta_sample")}</a>
        </div>
        <p className="mt-4 flex items-center justify-center gap-2 text-sm text-fg-2">
          <Languages size={15} /> {LOCALES.map((l) => l.native).join(" · ")} <span aria-hidden>·</span> <Search size={15} /> {t("p6_hero_search_free")}
        </p>
        <SourceLabel source={t("p6_source_onet")} asOf="2026-11-06" />
      </motion.section>

      <section className="mt-14"><TryIt /></section>

      <section id="sample" className="mt-14 scroll-mt-8">
        <h2 className="mb-6 text-center font-serif text-3xl">{t("p6_sample_heading")}</h2>
        <div className="mx-auto max-w-2xl"><SampleReport /></div>
      </section>

      <section className="mt-16 grid gap-4 md:mt-20 md:grid-cols-2">
        {FEATURES.map((feature) => (
          <div key={feature.titleKey} className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
            <div className="text-accent">{feature.icon}</div>
            <h2 className="mt-3 font-serif text-xl">{t(feature.titleKey)}</h2>
            <p className="mt-1 text-sm text-fg-2">{t(feature.bodyKey)}</p>
          </div>
        ))}
      </section>

      <section className="mt-16 md:mt-20">
        <h2 className="text-center font-serif text-3xl">{t("p6_diff_title")}</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {DIFFERENTIATORS.map((d) => (
            <div key={d.titleKey} className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
              <div className="text-accent">{d.icon}</div>
              <h3 className="mt-3 font-serif text-xl">{t(d.titleKey)}</h3>
              <p className="mt-1 text-sm text-fg-2">{t(d.bodyKey)}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-16 rounded-2xl border border-white/10 bg-white/[0.02] p-6 md:mt-20">
        <h2 className="flex items-center gap-2 font-serif text-2xl"><ShieldCheck className="text-accent" size={22} /> {t("p6_trust_title")}</h2>
        <ul className="mt-4 grid gap-3 text-sm text-fg-2 md:grid-cols-3">
          <li>{t("p6_trust_1")}</li>
          <li>{t("p6_trust_2")}</li>
          <li>{t("p6_trust_3")} <a className="underline" href="/methodology">{t("p6_methodology")}</a>.</li>
        </ul>
      </section>

      <section className="mt-16 md:mt-20">
        <h2 className="text-center font-serif text-3xl">{t("p6_how_title")}</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-4">
          {STEPS.map((step) => (
            <div key={step.n} className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
              <span className="font-serif text-3xl text-accent">{step.n}</span>
              <h3 className="mt-2 font-serif text-xl">{t(step.titleKey)}</h3>
              <p className="mt-1 text-sm text-fg-2">{t(step.bodyKey)}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="pricing" className="mt-16 scroll-mt-8 md:mt-20">
        <h2 className="text-center font-serif text-3xl">{t("p6_pricing_title")}</h2>
        <p className="mt-2 text-center text-sm text-fg-2">{t("p6_pricing_sub")}</p>
        <div className="mt-8"><Pricing /></div>
      </section>

      <section className="mt-16 md:mt-20">
        <h2 className="text-center font-serif text-3xl">{t("p6_faq_title")}</h2>
        <div className="mx-auto mt-8 max-w-2xl space-y-4">
          {FAQS.map((faq) => (
            <div key={faq.qKey} className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
              <h3 className="font-serif text-lg">{t(faq.qKey)}</h3>
              <p className="mt-1 text-sm text-fg-2">{t(faq.aKey)}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="mt-16 flex flex-col items-center gap-3 border-t border-white/10 pt-8 text-sm text-fg-2 md:mt-20">
        <span className="font-serif text-base text-white">Career Guidance AI</span>
        {/* Phase 8: the guest language switcher lives in the landing
            footer (the signed-in shells carry their own). Same pattern
            as components/shell.tsx: icon + native-name select. */}
        <label className="relative flex items-center gap-1.5 rounded-[var(--radius-sm)] p-2 text-fg-3 transition hover:bg-white/5 hover:text-white" title={t("language")}>
          <Languages size={16} />
          <select
            aria-label={t("language")}
            value={locale}
            onChange={(e) => setLocale(e.target.value as typeof locale)}
            className="bg-transparent text-xs text-fg-2 focus:outline-none"
          >
            {LOCALES.map((l) => (
              <option key={l.id} value={l.id} className="bg-bg-3 text-fg">
                {l.native}
              </option>
            ))}
          </select>
        </label>
        <div className="flex gap-5">
          <a href="/terms" className="hover:text-white">{t("p6_terms")}</a>
          <a href="/privacy" className="hover:text-white">{t("p6_privacy")}</a>
          <a href="/methodology" className="hover:text-white">{t("p6_methodology")}</a>
          <a href="/refund" className="hover:text-white">{t("p6_refunds")}</a>
        </div>
        <p className="max-w-xl text-center text-xs text-fg-3">
          {t("p6_onet_note")}
        </p>
      </footer>
    </main>
  );
}
