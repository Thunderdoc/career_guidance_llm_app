"use client";

/**
 * /report/[runId] (Phase 1): the hero report surface.
 *
 * Data sources, in order: (1) sessionStorage copy stashed by the /start
 * wizard or try-it box — this is what lets a GUEST see the report for the
 * run they just made, since anonymous runs belong to no account; (2) the
 * signed-in history API for saved runs. Phase 2 adds Reality Score,
 * why-not, alternatives and the parent version on top of this page.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n";
import type { Recommendation, RecommendResponse } from "@/lib/types";
import { ScoreMeter } from "./ui/score-meter";
import { SourceLabel } from "./ui/source-label";
import { EmptyState } from "./ui/empty-state";
import { Spinner } from "./ui";

export function ReportView({ runId: givenId }: { runId: string }) {
  // Export placeholder ("_") → the real id lives in the URL (see page.tsx).
  const runId = givenId === "_" && typeof window !== "undefined"
    ? (window.location.pathname.split("/").filter(Boolean).pop() ?? givenId)
    : givenId;
  const { t } = useI18n();
  const { user } = useAuth();
  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    try {
      const raw = window.sessionStorage.getItem(`cg.report.${runId}`);
      if (raw) { setResult(JSON.parse(raw) as RecommendResponse); return; }
    } catch { /* fall through to history */ }
    api.history()
      .then((h) => {
        if (cancelled) return;
        const run = h.runs.find((r) => String(r.id) === runId);
        if (!run) { setMissing(true); return; }
        setResult({
          run_id: run.id, provider: run.provider, is_demo: run.is_demo, used_fallback: false,
          priority_skills: [], detected_skills: [], unmatched_skills: [],
          weights: { skills: 0, interests: 0, job_zone: 0 }, recommendations: run.recommendations,
        });
      })
      .catch(() => { if (!cancelled) setMissing(true); });
    return () => { cancelled = true; };
  }, [runId]);

  if (missing) {
    return (
      <main className="mx-auto w-full max-w-3xl px-5 py-16">
        <EmptyState title={t("p1_report_title")} hint={t("p1_report_guest_note")}
          action={<a href="/start" className="rounded-xl bg-white px-5 py-3 text-sm font-medium text-black">{t("p1_start_title")}</a>} />
      </main>
    );
  }
  if (!result) return <main className="mx-auto max-w-3xl px-5 py-16"><Spinner label={t("connecting")} /></main>;

  return (
    <main className="mx-auto w-full max-w-3xl px-5 pb-20">
      <header className="flex items-center justify-between py-6">
        <Link href="/" className="font-serif text-xl">Career Guidance AI</Link>
        {!user && <a href={`/login?next=/report/${runId}`} className="rounded-xl border border-white/15 px-4 py-2 text-sm font-medium hover:bg-white/5">{t("p1_signin_save")}</a>}
      </header>
      <h1 className="font-serif text-3xl">{t("p1_report_title")}</h1>
      {result.anonymous && <p className="mt-2 text-sm text-fg-2">{t("p1_report_guest_note")}</p>}
      {result.priority_skills.length > 0 && (
        <p className="mt-4 text-sm"><span className="text-fg-2">{t("priority_skills")}:</span> <span className="font-medium">{result.priority_skills.join(" · ")}</span></p>
      )}
      <div className="mt-8 space-y-4">
        {result.recommendations.map((rec: Recommendation) => (
          <article key={rec.career_id} className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <h2 className="font-serif text-2xl">{rec.title}</h2>
              <span className="text-sm text-fg-2">{rec.suitability}</span>
            </div>
            <div className="mt-4 max-w-xs"><ScoreMeter value={rec.match_percent ?? Math.round(rec.match_score * 100)} label={t("results_title")} /></div>
            <p className="mt-4 text-sm text-fg-2">{rec.match_reason}</p>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 text-sm">
              <div><h3 className="font-medium">{t("matching")}</h3><p className="mt-1 text-fg-2">{rec.matching_skills.join(", ") || "—"}</p></div>
              <div><h3 className="font-medium">{t("missing")}</h3><p className="mt-1 text-fg-2">{rec.missing_skills.join(", ") || "—"}</p></div>
            </div>
            {rec.learning_path?.length > 0 && (
              <div className="mt-4 text-sm"><h3 className="font-medium">{t("learning_path")}</h3>
                <ol className="mt-1 list-decimal space-y-1 pl-5 text-fg-2">{rec.learning_path.slice(0, 5).map((s) => <li key={s}>{s}</li>)}</ol></div>
            )}
            <SourceLabel source="Source: O*NET occupational catalogue (974 occupations), this app's hybrid matcher" asOf="2026-11-06" />
          </article>
        ))}
      </div>
      <div className="mt-8 flex flex-wrap gap-3">
        <a href="/plan" className="rounded-xl bg-white px-5 py-3 text-sm font-medium text-black hover:bg-white/90">{t("nav_plan")}</a>
        <a href="/start" className="rounded-xl border border-white/15 px-5 py-3 text-sm font-medium hover:bg-white/5">{t("p1_start_title")}</a>
      </div>
    </main>
  );
}
