"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import type { AssessmentResult, Question } from "@/lib/types";
import { AnimatedGroup, TextEffect } from "./motion";

const SCALE = ["Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"];

export function AssessmentView({ onDone }: { onDone: (scores: Record<string, number>, code: string) => void }) {
  const [qs, setQs] = useState<Question[]>([]);
  const [i, setI] = useState(0);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [dir, setDir] = useState(1);
  const [result, setResult] = useState<AssessmentResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.questions().then((r) => setQs(r.questions)).catch((e) => setErr(e.message));
  }, []);

  const q = qs[i];
  const pct = qs.length ? Math.round((Object.keys(answers).length / qs.length) * 100) : 0;

  const answer = async (v: number) => {
    const next = { ...answers, [q.id]: v };
    setAnswers(next);
    if (i < qs.length - 1) {
      setDir(1);
      setTimeout(() => setI(i + 1), 180);
    } else {
      try {
        setResult(await api.assess(next));
      } catch (e) {
        setErr((e as Error).message);
      }
    }
  };

  if (err) return <p className="text-danger">{err}</p>;

  if (result) {
    const max = Math.max(...result.profile.map((p) => p.score));
    return (
      <div className="flex flex-col gap-6">
        <header className="text-center">
          <TextEffect as="h1" className="font-serif text-4xl">
            Your interest profile
          </TextEffect>
          <p className="mt-2 text-fg-2">
            Holland code <span className="mono rounded bg-bg-3 px-2 py-0.5 text-accent">{result.holland_code}</span>
          </p>
        </header>
        <AnimatedGroup className="flex flex-col gap-2" stagger={0.07}>
          {result.profile.map((p) => (
            <div key={p.dim} className="rounded-[var(--radius-md)] bg-bg-3 p-4 ring-1 ring-white/5">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium">
                  <span className="mono mr-2 text-accent">{p.dim}</span>
                  {p.name}
                </span>
                <span className="text-fg-2">{p.score.toFixed(1)} / 7</span>
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-bg-4">
                <motion.div className="h-full bg-accent" initial={{ width: 0 }} animate={{ width: `${(p.score / max) * 100}%` }} transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }} />
              </div>
              <p className="mt-2 text-xs text-fg-3">{p.blurb}</p>
            </div>
          ))}
        </AnimatedGroup>
        <div className="flex justify-center gap-3">
          <button onClick={() => { setResult(null); setAnswers({}); setI(0); }} className="rounded-full bg-bg-3 px-4 py-2 text-sm text-fg-2 hover:text-fg">
            Retake
          </button>
          <button onClick={() => onDone(result.scores, result.holland_code)} className="inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2 text-sm font-medium text-black shadow-[0_0_24px_rgba(0,212,170,0.3)]">
            Use in recommendations <ArrowRight size={14} />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <header className="text-center">
        <TextEffect as="h1" className="font-serif text-4xl">
          What kind of work energises you?
        </TextEffect>
        <p className="mt-2 text-sm text-fg-2">18 quick statements · about 2 minutes · blends into your career matches</p>
      </header>

      <div className="h-1 overflow-hidden rounded-full bg-bg-3">
        <motion.div className="h-full bg-accent" animate={{ width: `${pct}%` }} transition={{ duration: 0.4 }} />
      </div>

      <div className="relative min-h-[260px] overflow-hidden rounded-[var(--radius-lg)] bg-bg-3 p-6 ring-1 ring-white/5 sm:p-8">
        <AnimatePresence mode="wait" custom={dir}>
          {q && (
            <motion.div
              key={q.id}
              custom={dir}
              initial={{ opacity: 0, x: dir * 40, filter: "blur(4px)" }}
              animate={{ opacity: 1, x: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, x: -dir * 40, filter: "blur(4px)" }}
              transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
            >
              <div className="mono text-xs text-fg-3">
                {i + 1} / {qs.length}
              </div>
              <p className="mt-2 text-xl font-medium leading-snug sm:text-2xl">{q.text}</p>
              <div className="mt-6 grid grid-cols-5 gap-2">
                {SCALE.map((label, idx) => {
                  const v = idx + 1;
                  const sel = answers[q.id] === v;
                  return (
                    <button
                      key={v}
                      onClick={() => answer(v)}
                      className={cn(
                        "group flex flex-col items-center gap-2 rounded-[var(--radius-md)] border px-2 py-3 text-center transition",
                        sel ? "border-accent bg-accent/15 text-accent" : "border-white/10 text-fg-2 hover:border-accent/40 hover:bg-bg-4 hover:text-fg",
                      )}
                    >
                      <span className={cn("grid h-7 w-7 place-items-center rounded-full border text-xs", sel ? "border-accent bg-accent text-black" : "border-white/20 group-hover:border-accent/60")}>
                        {sel ? <Check size={14} /> : v}
                      </span>
                      <span className="hidden text-[11px] leading-tight sm:block">{label}</span>
                    </button>
                  );
                })}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <div className="flex justify-between text-sm">
        <button disabled={i === 0} onClick={() => { setDir(-1); setI(i - 1); }} className="inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-fg-2 transition hover:bg-bg-3 hover:text-fg disabled:opacity-30">
          <ArrowLeft size={14} /> Back
        </button>
        <button disabled={!answers[q?.id] || i >= qs.length - 1} onClick={() => { setDir(1); setI(i + 1); }} className="inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-fg-2 transition hover:bg-bg-3 hover:text-fg disabled:opacity-30">
          Next <ArrowRight size={14} />
        </button>
      </div>
    </div>
  );
}
