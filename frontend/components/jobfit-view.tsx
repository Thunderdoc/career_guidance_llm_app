"use client";

import { motion } from "motion/react";
import { ArrowUp, ExternalLink } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { AnimatedGroup, ProgressRing, TextEffect } from "./motion";

export function JobFitView() {
  const [skills, setSkills] = useState("");
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Awaited<ReturnType<typeof api.jobFit>> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const can = skills.trim().length > 2 && jd.trim().length > 20 && !busy;

  const run = async () => {
    if (!can) return;
    setBusy(true);
    setErr(null);
    try {
      setRes(await api.jobFit(skills, "", jd));
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <header className="text-center">
        <TextEffect as="h1" className="font-serif text-4xl">
          How ready are you for this job?
        </TextEffect>
        <p className="mt-2 text-sm text-fg-2">Paste a job description. We extract its skills and compare them with yours.</p>
      </header>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs text-fg-2">
          Your skills
          <textarea value={skills} onChange={(e) => setSkills(e.target.value)} rows={8} placeholder="Python, SQL, Excel…" className="rounded-[var(--radius-lg)] bg-bg-3 p-3 text-sm text-fg ring-1 ring-white/5 placeholder:text-fg-3 focus:outline-none focus:ring-accent" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-fg-2">
          Job description
          <textarea value={jd} onChange={(e) => setJd(e.target.value)} rows={8} placeholder="Paste the full posting…" className="rounded-[var(--radius-lg)] bg-bg-3 p-3 text-sm text-fg ring-1 ring-white/5 placeholder:text-fg-3 focus:outline-none focus:ring-accent" />
        </label>
      </div>
      <div className="flex justify-end">
        <button onClick={run} disabled={!can} className={cn("inline-flex items-center gap-2 rounded-full px-5 py-2 text-sm font-medium transition", can ? "bg-accent text-black shadow-[0_0_24px_rgba(0,212,170,0.3)]" : "bg-bg-3 text-fg-3")}>
          {busy ? <span className="h-4 w-4 rounded-full border-2 border-black/30 border-t-black loading-ring" /> : <ArrowUp size={16} />} Check fit
        </button>
      </div>
      {err && <p className="text-sm text-danger">{err}</p>}

      {res && (
        <motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="rounded-[var(--radius-lg)] bg-panel p-6 ring-1 ring-white/5">
          <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-start">
            <ProgressRing value={res.readiness} size={128} stroke={10} label="ready" />
            <div className="flex-1">
              <AnimatedGroup className="grid gap-4 sm:grid-cols-2" stagger={0.1}>
                <div>
                  <div className="mb-1.5 text-[11px] uppercase tracking-wider text-fg-3">Matched ({res.matched.length})</div>
                  <div className="flex flex-wrap gap-1.5">
                    {res.matched.map((s) => (
                      <span key={s} className="rounded-[var(--radius-sm)] bg-ok/10 px-2 py-0.5 text-xs text-[#8fe6a7] ring-1 ring-ok/20">
                        {s}
                      </span>
                    ))}
                    {res.matched.length === 0 && <span className="text-xs text-fg-3">None yet</span>}
                  </div>
                </div>
                <div>
                  <div className="mb-1.5 text-[11px] uppercase tracking-wider text-fg-3">Missing ({res.missing.length})</div>
                  <div className="flex flex-wrap gap-1.5">
                    {res.missing.map((s) => (
                      <span key={s} className="rounded-[var(--radius-sm)] bg-gold/10 px-2 py-0.5 text-xs text-[#f1c777] ring-1 ring-gold/20">
                        {s}
                      </span>
                    ))}
                    {res.missing.length === 0 && <span className="text-xs text-fg-3">Nothing missing 🎉</span>}
                  </div>
                </div>
              </AnimatedGroup>
              {res.resources.length > 0 && (
                <div className="mt-4">
                  <div className="mb-1.5 text-[11px] uppercase tracking-wider text-fg-3">Start here</div>
                  <div className="space-y-1.5">
                    {res.resources.map((r) => (
                      <a key={r.url} href={r.url} target="_blank" rel="noopener noreferrer" className="flex items-center justify-between rounded-[var(--radius-md)] bg-bg-3 px-3 py-2 text-sm hover:bg-bg-4">
                        <span>
                          {r.title} <span className="text-xs text-fg-3">· {r.provider}</span>
                        </span>
                        <ExternalLink size={13} className="text-fg-3" />
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </motion.section>
      )}
    </div>
  );
}
