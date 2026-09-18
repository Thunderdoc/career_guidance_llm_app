"use client";

/**
 * `/resume` — rule-based résumé scorer.
 *
 * Upload a PDF/TXT/MD (server extracts text) or paste it, pick a target career
 * and get six signals: keyword coverage, action verbs, quantified impact,
 * sections, experience and readability — each with a rewrite suggestion.
 */

import { FileText, Upload, Wand2 } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ResumeScore } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { AnimatedNumber, ProgressRing } from "./motion";
import {
  Badge,
  Button,
  Card,
  Field,
  PageHeader,
  Progress,
  SourceLabel,
  Spinner,
  Stat,
  inputCls,
} from "./ui";

export function ResumeView() {
  const { t } = useI18n();
  const [text, setText] = useState("");
  const [careerId, setCareerId] = useState("");
  const [careerQuery, setCareerQuery] = useState("");
  const [careers, setCareers] = useState<{ id: string; title: string }[]>([]);
  const [result, setResult] = useState<ResumeScore | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (careerQuery.trim().length < 3) return setCareers([]);
    api
      .searchCareers(careerQuery, 6)
      .then((r) => setCareers(r.results))
      .catch(() => setCareers([]));
  }, [careerQuery]);

  const upload = async (file: File) => {
    setBusy(true);
    try {
      const r = await api.extractResume(file);
      setText(r.text);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const analyse = async () => {
    setBusy(true);
    setError("");
    try {
      setResult(await api.scoreResume({ resume_text: text, target_career_id: careerId || undefined }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("resume_title")} subtitle={t("resume_sub")} source={t("resume_source")} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-serif text-xl">{t("resume_input_title")}</h2>
            <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-white/12 px-3 py-1.5 text-xs text-fg-2 hover:border-accent/40">
              <Upload size={14} />
              {t("resume_upload")}
              <input
                type="file"
                accept=".pdf,.txt,.md"
                className="sr-only"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void upload(file);
                }}
              />
            </label>
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={12}
            className={`${inputCls} mt-3 font-mono text-xs`}
            placeholder={t("resume_placeholder")}
            aria-label={t("resume_input_title")}
          />
          <p className="mt-1 text-[11px] text-fg-3">
            {text.length} {t("resume_chars")} · {t("resume_privacy")}
          </p>
        </Card>

        <Card className="flex flex-col gap-4">
          <Field label={t("resume_target")} hint={t("resume_target_hint")}>
            <input
              className={inputCls}
              value={careerQuery}
              onChange={(e) => {
                setCareerQuery(e.target.value);
                setCareerId("");
              }}
              placeholder={t("onb_target_ph")}
            />
          </Field>
          {careers.length > 0 && !careerId && (
            <div className="flex flex-col gap-1">
              {careers.map((c) => (
                <button
                  key={c.id}
                  onClick={() => {
                    setCareerId(c.id);
                    setCareerQuery(c.title);
                    setCareers([]);
                  }}
                  className="rounded-lg border border-white/10 px-3 py-2 text-left text-sm text-fg-2 hover:border-accent/40"
                >
                  {c.title}
                </button>
              ))}
            </div>
          )}
          <Button onClick={analyse} disabled={busy || text.trim().length < 40}>
            <Wand2 size={15} /> {busy ? t("analysing") : t("resume_analyse")}
          </Button>
          {error && (
            <p role="alert" className="text-xs text-danger">
              {error}
            </p>
          )}
          <SourceLabel text={t("resume_signals")} />
        </Card>
      </div>

      {busy && !result && <Spinner label={t("resume_analysing")} />}

      {result && (
        <>
          <Card>
            <div className="flex flex-wrap items-center gap-6">
              <ProgressRing value={result.score} size={110} label={t("resume_score_label")} />
              <div className="min-w-0 flex-1">
                <p className="font-serif text-2xl">
                  <AnimatedNumber value={result.score} />/100 · {result.grade}
                </p>
                <p className="mt-1 text-sm text-fg-2">
                  {result.target_career ? `${t("resume_target")}: ${result.target_career.title}` : t("resume_no_target")}
                </p>
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <div>
                    <p className="text-xs text-fg-3">
                      {t("resume_keywords")} · {result.keyword_coverage.percent}%
                    </p>
                    <Progress percent={result.keyword_coverage.percent} label={t("resume_keywords")} />
                  </div>
                  <div>
                    <p className="text-xs text-fg-3">
                      {t("resume_impact")} · {result.quantified_impact.quantified}/{result.quantified_impact.bullets}
                    </p>
                    <Progress percent={result.quantified_impact.percent} label={t("resume_impact")} />
                  </div>
                </div>
              </div>
            </div>
            <SourceLabel text={result.source} />
          </Card>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <h2 className="font-serif text-xl">{t("resume_keywords")}</h2>
              {result.keyword_coverage.matched.length > 0 && (
                <>
                  <p className="mt-2 text-xs uppercase tracking-wide text-fg-3">{t("matching")}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {result.keyword_coverage.matched.map((s) => (
                      <Badge key={s} tone="ok">
                        {s}
                      </Badge>
                    ))}
                  </div>
                </>
              )}
              {result.missing_keywords.length > 0 && (
                <>
                  <p className="mt-3 text-xs uppercase tracking-wide text-fg-3">{t("missing")}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {result.missing_keywords.slice(0, 12).map((s) => (
                      <Badge key={s} tone="danger">
                        {s}
                      </Badge>
                    ))}
                  </div>
                </>
              )}
              <SourceLabel text={t("resume_keyword_source")} />
            </Card>

            <Card>
              <h2 className="font-serif text-xl">{t("resume_sections")}</h2>
              <ul className="mt-3 flex flex-col gap-1 text-sm">
                {result.sections.map((s) => (
                  <li key={s.name} className="flex items-center justify-between">
                    <span className="text-fg-2">{s.name}</span>
                    <span className={s.found ? "text-ok" : "text-danger"}>{s.found ? t("found") : t("not_found")}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <Stat label={t("resume_years")} value={result.detected_years || "—"} />
                <Stat label={t("resume_verbs")} value={result.action_verbs.found.length} />
              </div>
              <SourceLabel text={t("resume_section_source")} />
            </Card>

            <Card>
              <h2 className="font-serif text-xl">{t("resume_rewrites")}</h2>
              {result.rewrites.length === 0 ? (
                <p className="mt-2 text-sm text-fg-3">{t("resume_no_rewrites")}</p>
              ) : (
                <ul className="mt-3 flex flex-col gap-2 text-xs">
                  {result.rewrites.map((r) => (
                    <li key={r.original + r.suggestion} className="rounded-xl border border-white/8 p-3">
                      <p className="text-fg-3 line-through">{r.original.slice(0, 120)}</p>
                      <p className="mt-1 text-fg">{r.suggestion.slice(0, 160)}</p>
                      <p className="mt-1 text-fg-3">{r.reason}</p>
                    </li>
                  ))}
                </ul>
              )}
              <SourceLabel text={t("resume_rewrite_source")} />
            </Card>
          </div>

          <Card>
            <div className="flex items-center gap-2">
              <FileText size={16} className="text-accent" />
              <h2 className="font-serif text-xl">{t("resume_next_title")}</h2>
            </div>
            <ul className="mt-2 flex flex-col gap-1 text-sm text-fg-2">
              <li>· {t("resume_next_1")}</li>
              <li>· {t("resume_next_2")}</li>
              <li>· {t("resume_next_3")}</li>
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
