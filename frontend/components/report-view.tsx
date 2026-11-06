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
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useBandwidth } from "@/lib/bandwidth-context";
import { useI18n } from "@/lib/i18n";
import { BandwidthToggle } from "./bandwidth-toggle";
import { pathway } from "@/lib/api";
import type { Recommendation, RecommendResponse } from "@/lib/types";
import { ScoreMeter } from "./ui/score-meter";
import { SourceLabel } from "./ui/source-label";
import { EmptyState } from "./ui/empty-state";
import { Spinner } from "./ui";

// Phase 7: chat panel is code-split — it must not grow /report first-load JS.
const ChatPanel = dynamic(() => import("./chat-panel").then((m) => m.ChatPanel), {
  ssr: false,
});

// Phase 8: share panel is code-split for the same reason.
const SharePanel = dynamic(() => import("./share-panel").then((m) => m.SharePanel), {
  ssr: false,
});

export function ReportView({ runId: givenId }: { runId: string }) {
  // Export placeholder ("_") → the real id lives in the URL (see page.tsx).
  const runId = givenId === "_" && typeof window !== "undefined"
    ? (window.location.pathname.split("/").filter(Boolean).pop() ?? givenId)
    : givenId;
  const { t } = useI18n();
  const { user } = useAuth();
  const [result, setResult] = useState<RecommendResponse | null>(null);
  const [missing, setMissing] = useState(false);
  const [parent, setParent] = useState(false);
  const [review, setReview] = useState<{ note: string } | null>(null);
  // Phase 8: in low-bandwidth mode the heavy dynamic panels (chat,
  // share) are not mounted — and their chunks not fetched — until the
  // user explicitly loads them.
  const { lowBandwidth } = useBandwidth();
  const [chatOn, setChatOn] = useState(false);
  const [shareOn, setShareOn] = useState(false);

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
        if (run.counsellor_review) setReview({ note: run.counsellor_review.note });
        setResult({
          run_id: run.id, provider: run.provider, is_demo: run.is_demo, used_fallback: false,
          priority_skills: [], detected_skills: [], unmatched_skills: [],
          weights: { skills: 0, interests: 0, job_zone: 0 }, recommendations: run.recommendations,
        });
      })
      .catch(() => { if (!cancelled) setMissing(true); });
    return () => { cancelled = true; };
  }, [runId]);

  const fmtInr = (range?: number[]) => range && range.length === 2 ? `₹${range[0].toLocaleString("en-IN")} – ₹${range[1].toLocaleString("en-IN")}` : "—";
  const sharePng = async () => {
    const top = result?.recommendations[0]; if (!top) return;
    const canvas = document.createElement("canvas"); canvas.width = 1080; canvas.height = 1080;
    const ctx = canvas.getContext("2d"); if (!ctx) return;
    ctx.fillStyle = "#111"; ctx.fillRect(0, 0, 1080, 1080);
    ctx.fillStyle = "#fff"; ctx.font = "bold 64px sans-serif"; ctx.fillText("Career Guidance AI", 70, 130);
    ctx.font = "52px sans-serif"; ctx.fillText(top.title.slice(0, 34), 70, 260);
    ctx.font = "40px sans-serif";
    ctx.fillText(`Match: ${Math.round(top.match_percent ?? top.match_score * 100)}%`, 70, 360);
    if (top.reality?.score != null) ctx.fillText(`${t("p2_reality")}: ${Math.round(top.reality.score)}/100`, 70, 430);
    const m = top.reality?.india.market;
    if (m) { ctx.font = "34px sans-serif"; ctx.fillText(`${t("p2_fresher")}: ${fmtInr(m.fresher_salary_inr)}`, 70, 540); ctx.fillText(`${t("p2_7yr")}: ${fmtInr(m.salary_7yr_inr)}`, 70, 600); }
    ctx.font = "28px sans-serif"; ctx.fillStyle = "#aaa"; ctx.fillText(t("p2_estimate_note"), 70, 980);
    const a = document.createElement("a"); a.download = "career-report-card.png"; a.href = canvas.toDataURL("image/png"); a.click();
  };
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
        <div className="flex items-center gap-2">
          <BandwidthToggle variant="compact" />
          {!user && <a href={`/login?next=/report/${runId}`} className="rounded-xl border border-white/15 px-4 py-2 text-sm font-medium hover:bg-white/5">{t("p1_signin_save")}</a>}
        </div>
      </header>
      <h1 className="font-serif text-3xl">{t("p1_report_title")}</h1>
      {review && (
        <p className="mt-3 rounded-xl border border-white/10 p-3 text-sm">
          <span className="font-medium">{t("p4_reviewed_by")}</span>
          {review.note && <span className="text-fg-2"> — {review.note}</span>}
        </p>
      )}
      {result.anonymous && <p className="mt-2 text-sm text-fg-2">{t("p1_report_guest_note")}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button onClick={() => setParent(!parent)} className="rounded-xl border border-white/15 px-4 py-2 text-sm font-medium hover:bg-white/5">{parent ? t("p2_parent_off") : t("p2_parent")}</button>
        {user ? <a href={pathway.reportUrl()} className="rounded-xl border border-white/15 px-4 py-2 text-sm font-medium hover:bg-white/5">{t("p2_download_pdf")}</a> : <a href={`/login?next=/report/${runId}`} className="rounded-xl border border-white/15 px-4 py-2 text-sm font-medium hover:bg-white/5">{t("p2_download_pdf")}</a>}
        <button onClick={sharePng} className="rounded-xl border border-white/15 px-4 py-2 text-sm font-medium hover:bg-white/5">{t("p2_share_png")}</button>
        <a href="#share" className="rounded-xl border border-white/15 px-4 py-2 text-sm font-medium hover:bg-white/5">{t("p8_share_button")}</a>
      </div>
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
            {rec.reality && (
              <div className="mt-5 rounded-xl border border-white/10 p-4">
                <div className="max-w-xs"><ScoreMeter value={rec.reality.score ?? 0} label={t("p2_reality")} /></div>
                <p className="mt-1 text-xs text-fg-2">{t("p2_confidence").replace("{n}", String(Math.round(rec.reality.confidence * 100)))}</p>
                <div className="mt-3 space-y-2">
                  {rec.reality.components.map((c) => (
                    <div key={c.key} className="text-sm">
                      {c.value != null ? <ScoreMeter value={c.value} label={c.label} /> : <p className="text-fg-2">{c.label}: {t("p2_insufficient")}</p>}
                      <p className="text-xs text-fg-3">{c.explanation}</p>
                    </div>
                  ))}
                </div>
                {rec.reality.india.crosswalk.mapped && <p className="mt-3 text-xs text-fg-2">{t("p2_nco")}: {rec.reality.india.crosswalk.nco_code} ({rec.reality.india.crosswalk.confidence})</p>}
                {rec.reality.india.market && (
                  <div className="mt-3 text-sm">
                    <h3 className="font-medium">{parent ? t("p2_parent_cost") : t("p2_salary_ladder")}</h3>
                    <ul className="mt-1 space-y-1 text-fg-2">
                      <li>{t("p2_fresher")}: {fmtInr(rec.reality.india.market.fresher_salary_inr)}</li>
                      <li>{t("p2_3yr")}: {fmtInr(rec.reality.india.market.salary_3yr_inr)}</li>
                      <li>{t("p2_7yr")}: {fmtInr(rec.reality.india.market.salary_7yr_inr)}</li>
                    </ul>
                    {parent && <p className="mt-2 text-fg-2">{t("p2_parent_time")}: {rec.reality.components.find((c) => c.key === "time_to_first_job")?.explanation ?? "—"}<br />{t("p2_parent_risk")}: {rec.reality.components.find((c) => c.key === "barrier_to_entry")?.explanation ?? ""} {rec.reality.components.find((c) => c.key === "ai_exposure")?.explanation ?? ""}</p>}
                    <div className="mt-2 flex flex-wrap gap-1">{rec.reality.india.market.top_cities.map((x) => <span key={x} className="rounded-full bg-white/10 px-2 py-0.5 text-xs">{x}</span>)}</div>
                    <p className="mt-1 text-xs text-fg-3">{t("p2_cities")} · {t("p2_sectors")}: {rec.reality.india.market.top_sectors.join(", ")}</p>
                    <SourceLabel source={rec.reality.india.market.source} asOf={rec.reality.india.market.as_of} />
                    <p className="text-[11px] text-fg-3">{t("p2_estimate_note")}</p>
                  </div>
                )}
              </div>
            )}
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
      {(result.why_not?.length ?? 0) > 0 && (
        <section className="mt-8 rounded-2xl border border-white/10 p-6"><h2 className="font-serif text-2xl">{t("p2_why_not")}</h2>
          {result.why_not!.map((w) => <div key={w.career_id} className="mt-3 text-sm"><p className="font-medium">{w.title} — {w.match_percent}%</p><p className="text-fg-2">{w.explanation}</p><SourceLabel source={w.source} /></div>)}
        </section>
      )}
      {(result.alternatives?.length ?? 0) > 0 && (
        <section className="mt-6 rounded-2xl border border-white/10 p-6"><h2 className="font-serif text-2xl">{t("p2_alternatives")}</h2>
          <ul className="mt-3 space-y-2 text-sm">{result.alternatives!.map((a) => <li key={a.career_id}><span className="font-medium">{a.title}</span>{a.delta_skills.length > 0 && <span className="text-fg-2"> — {a.delta_skills.join(", ")}</span>}</li>)}</ul>
        </section>
      )}
      {Number.isFinite(Number(runId)) && (!lowBandwidth || shareOn ? (
        <SharePanel runId={result.run_id ?? Number(runId)} />
      ) : (
        <section id="share" className="mb-6 rounded-3xl border border-white/10 bg-white/[0.02] p-6">
          <h2 className="font-serif text-xl">{t("p8_share_title")}</h2>
          <p className="mt-1 text-sm text-fg-2">{t("p8_bw_share_deferred")}</p>
          <button type="button" onClick={() => setShareOn(true)} className="mt-3 rounded-xl bg-white px-4 py-2 text-sm font-semibold text-black">
            {t("p8_share_button")}
          </button>
        </section>
      ))}
      {Number.isFinite(Number(runId)) && (!lowBandwidth || chatOn ? (
        <ChatPanel runId={result.run_id ?? Number(runId)} />
      ) : (
        <section className="mb-6 rounded-3xl border border-white/10 bg-white/[0.02] p-6">
          <h2 className="font-serif text-xl">{t("p7_chat_title")}</h2>
          <p className="mt-1 text-sm text-fg-2">{t("p8_bw_chat_deferred")}</p>
          <button type="button" onClick={() => setChatOn(true)} className="mt-3 rounded-xl bg-white px-4 py-2 text-sm font-semibold text-black">
            {t("p8_bw_load_chat")}
          </button>
        </section>
      ))}
      <div className="mt-8 flex flex-wrap gap-3">
        <a href="/plan" className="rounded-xl bg-white px-5 py-3 text-sm font-medium text-black hover:bg-white/90">{t("nav_plan")}</a>
        <a href="/start" className="rounded-xl border border-white/15 px-5 py-3 text-sm font-medium hover:bg-white/5">{t("p1_start_title")}</a>
      </div>
    </main>
  );
}
