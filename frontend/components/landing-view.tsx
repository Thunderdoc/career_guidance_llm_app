"use client";

/**
 * Public landing page (sell-standard).
 *
 * Copy is English-only for v1; the signed-in app itself stays trilingual
 * (en/ta/hi). Pricing comes from /api/v1/billing/plans — an unset price
 * renders as "Contact us", never an invented number. No testimonials, no
 * user counts, no claims the product cannot prove.
 */
import { motion } from "motion/react";
import { ArrowRight, Check, Compass, FileText, Languages, Route, Search, Target } from "lucide-react";
import { useEffect, useState } from "react";
import { billingApi, type BillingPlan } from "@/lib/api";
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

const STEPS = [
  { n: "1", title: "Tell us your skills", body: "Skills, interests, education and experience — two minutes." },
  { n: "2", title: "Get 5 matched careers", body: "Each with matching skills, missing skills and a learning path." },
  { n: "3", title: "Follow the roadmap", body: "Track progress week by week until the gap closes." },
];

const FAQS = [
  {
    q: "Where does the career data come from?",
    a: "A catalogue of 974 occupations with skills, tasks and requirements, plus curated market data for India. AI features are optional, labelled, and never presented as facts.",
  },
  {
    q: "Do I need an account?",
    a: "Searching careers is public. Saving plans, history and progress needs a free account (Google or email magic link).",
  },
  {
    q: "Which languages are supported?",
    a: "The app works in English, Tamil and Hindi.",
  },
  {
    q: "Is my data private?",
    a: "Your runs, plans and progress belong to your account only. You can export everything or delete your account from Settings.",
  },
];

function priceLabel(plan: BillingPlan): string {
  if (plan.price_inr === 0) return "Free";
  if (plan.price_inr === null) return "Contact us";
  return `₹${plan.price_inr}/month`;
}

function Pricing() {
  const [plans, setPlans] = useState<BillingPlan[] | null>(null);
  const [error, setError] = useState("");

  const load = () => {
    setError("");
    billingApi
      .plans()
      .then((res) => setPlans(res.plans))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load pricing."));
  };

  useEffect(load, []);

  if (error) return <ErrorNote error={error} retry={load} />;
  if (!plans) return <Spinner label="Loading pricing…" />;

  return (
    <div className="grid gap-4 md:grid-cols-3">
      {plans.map((plan) => (
        <div
          key={plan.id}
          className={`rounded-2xl border p-6 ${
            plan.id === "pro" ? "border-accent/60 bg-white/[0.04]" : "border-white/10 bg-white/[0.02]"
          }`}
        >
          <h3 className="font-serif text-2xl">{plan.name}</h3>
          <p className="mt-1 text-sm text-fg-2">{plan.tagline}</p>
          <p className="mt-4 text-3xl font-semibold">{priceLabel(plan)}</p>
          {plan.id === "pro" && plan.trial_days > 0 && (
            <p className="mt-1 text-sm text-accent">Includes a {plan.trial_days}-day free trial.</p>
          )}
          <ul className="mt-5 space-y-2">
            {plan.features.map((feature) => (
              <li key={feature} className="flex gap-2 text-sm text-fg-2">
                <Check size={16} className="mt-0.5 shrink-0 text-accent" />
                <span>{feature}</span>
              </li>
            ))}
          </ul>
          <a
            href="/login"
            className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-white px-4 py-3 text-sm font-medium text-black transition hover:bg-white/90"
          >
            Get started <ArrowRight size={16} />
          </a>
        </div>
      ))}
    </div>
  );
}

export function LandingView() {
  return (
    <main className="mx-auto w-full max-w-5xl px-5 pb-20">
      <header className="flex items-center justify-between py-6">
        <span className="font-serif text-xl">Career Guidance AI</span>
        <a href="/login" className="rounded-xl border border-white/15 px-4 py-2 text-sm font-medium transition hover:bg-white/5">
          Sign in
        </a>
      </header>

      <motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="pt-10 text-center md:pt-16">
        <h1 className="mx-auto max-w-2xl font-serif text-4xl leading-tight md:text-5xl">
          Find a career that fits your skills.
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-base text-fg-2">
          Skill-gap analysis, career ladders and learning roadmaps across 974 occupations —
          grounded in real occupation data, in English, Tamil and Hindi.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <a
            href="/login"
            className="flex items-center gap-2 rounded-xl bg-white px-6 py-3 text-sm font-medium text-black transition hover:bg-white/90"
          >
            Get started free <ArrowRight size={16} />
          </a>
          <a href="#pricing" className="rounded-xl border border-white/15 px-6 py-3 text-sm font-medium transition hover:bg-white/5">
            See pricing
          </a>
        </div>
        <p className="mt-4 flex items-center justify-center gap-2 text-sm text-fg-2">
          <Languages size={15} /> English · Tamil · Hindi <span aria-hidden>·</span> <Search size={15} /> Career search is free, no account needed
        </p>
      </motion.section>

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
        <h2 className="text-center font-serif text-3xl">How it works</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
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
        <div className="mt-8">
          <Pricing />
        </div>
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
      </footer>
    </main>
  );
}
