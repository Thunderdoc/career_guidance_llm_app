"use client";

/**
 * /shared/[token] (Phase 8): the public, read-only view of a shared
 * report. Renders ONLY what GET /api/v1/shared/{token} returns — an
 * allowlist projection built server-side (career titles, match scores,
 * skills have/missing, Reality Score + labelled-estimate salary ladder,
 * learning path). The API never sends the owner's name/e-mail/handle,
 * constraints, raw profile text, institute info or counsellor notes, so
 * there is nothing here to hide — the absence is by construction.
 *
 * States: loading → report; 410 (expired/revoked) and 404 (unknown) get
 * distinct honest empty states. No sign-in is asked for, ever.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, sharingApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { SharedReport } from "@/lib/types";
import { ScoreMeter } from "./ui/score-meter";
import { SourceLabel } from "./ui/source-label";
import { EmptyState } from "./ui/empty-state";
import { Spinner } from "./ui";

export function SharedReportView({ token: given }: { token: string }) {
  const token =
    given === "_" && typeof window !== "undefined"
      ? (window.location.pathname.split("/").filter(Boolean).pop() ?? given)
      : given;
  const { t, locale } = useI18n();
  const [report, setReport] = useState<SharedReport | null>(null);
  const [status, setStatus] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    sharingApi
      .shared(token)
      .then((res) => { if (!cancelled) setReport(res); })
      .catch((e: unknown) => {
        if (!cancelled) setStatus(e instanceof ApiError ? e.status : 0);
      });
    return () => { cancelled = true; };
  }, [token]);

  const fmtInr = (range?: number[]) =>
    range && range.length === 2
      ? `₹${range[0].toLocaleString("en-IN")} – ₹${range[1].toLocaleString("en-IN")}`
      : "—";
  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleDateString(locale === "en" ? "en-IN" : locale, {
      day: "numeric", month: "short", year: "numeric",
    });

  if (status === 410) {
    return (
      <main className="mx-auto w-full max-w-3xl px-5 py-16">
        <EmptyState title={t("p8_shared_gone")} hint={t("p8_shared_ask_new")} />
      </main>
    );
  }
  if (status !== null) {
    return (
      <main className="mx-auto w-full max-w-3xl px-5 py-16">
        <EmptyState title={t("p8_shared_not_found")} hint={t("p8_shared_ask_new")} />
      </main>
    );
  }
  if (!report) {
    return <main className="mx-auto max-w-3xl px-5 py-16"><Spinner label={t("connecting")} /></main>;
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-5 pb-20">
      <header className="flex items-center justify-between py-6">
        <Link href="/" className="font-serif text-xl">Career Guidance AI</Link>
      </header>
      <p className="rounded-xl border border-accent/40 bg-accent/10 px-4 py-2 text-sm font-medium">
        {t("p8_shared_banner")}
      </p>
      <h1 className="mt-4 font-serif text-3xl">{t("p8_shared_title")}</h1>
      <p className="mt-2 text-sm text-fg-2">{t("p8_shared_expires", { date: fmtDate(report.expires_at) })}</p>
      {report.priority_skills.length > 0 && (
        <p className="mt-4 text-sm">
          <span className="text-fg-2">{t("priority_skills")}:</span>{" "}
          <span className="font-medium">{report.priority_skills.join(" · ")}</span>
        </p>
      )}
      <div className="mt-8 space-y-4">
        {report.recommendations.map((rec) => (
          <article key={rec.career_id || rec.title} className="rounded-2xl border border-white/10 bg-white/[0.02] p-6">
            <h2 className="font-serif text-2xl">{rec.title}</h2>
            <div className="mt-4 max-w-xs">
              <ScoreMeter value={rec.match_percent} label={t("results_title")} />
            </div>
            {rec.reality && (
              <div className="mt-5 rounded-xl border border-white/10 p-4">
                <div className="max-w-xs">
                  <ScoreMeter value={rec.reality.score ?? 0} label={t("p2_reality")} />
                </div>
                <p className="mt-1 text-xs text-fg-2">
                  {t("p2_confidence").replace("{n}", String(Math.round(rec.reality.confidence * 100)))}
                </p>
                {rec.reality.salary_ladder && (
                  <div className="mt-3 text-sm">
                    <h3 className="font-medium">{t("p2_salary_ladder")}</h3>
                    <ul className="mt-1 space-y-1 text-fg-2">
                      <li>{t("p2_fresher")}: {fmtInr(rec.reality.salary_ladder.fresher_salary_inr)}</li>
                      <li>{t("p2_3yr")}: {fmtInr(rec.reality.salary_ladder.salary_3yr_inr)}</li>
                      <li>{t("p2_7yr")}: {fmtInr(rec.reality.salary_ladder.salary_7yr_inr)}</li>
                    </ul>
                    <SourceLabel
                      source={rec.reality.salary_ladder.source}
                      asOf={rec.reality.salary_ladder.as_of}
                    />
                    <p className="text-[11px] text-fg-3">{t("p2_estimate_note")}</p>
                  </div>
                )}
              </div>
            )}
            <div className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
              <div>
                <h3 className="font-medium">{t("matching")}</h3>
                <p className="mt-1 text-fg-2">{rec.matching_skills.join(", ") || "—"}</p>
              </div>
              <div>
                <h3 className="font-medium">{t("missing")}</h3>
                <p className="mt-1 text-fg-2">{rec.missing_skills.join(", ") || "—"}</p>
              </div>
            </div>
            {rec.learning_path.length > 0 && (
              <div className="mt-4 text-sm">
                <h3 className="font-medium">{t("learning_path")}</h3>
                <ol className="mt-1 list-decimal space-y-1 pl-5 text-fg-2">
                  {rec.learning_path.slice(0, 5).map((s) => <li key={s}>{s}</li>)}
                </ol>
              </div>
            )}
            <SourceLabel source={report.source} />
          </article>
        ))}
      </div>
      <div className="mt-8">
        <a href="/start" className="rounded-xl bg-white px-5 py-3 text-sm font-medium text-black hover:bg-white/90">
          {t("p1_start_title")}
        </a>
      </div>
    </main>
  );
}
