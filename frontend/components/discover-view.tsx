"use client";

/**
 * `/discover` — the 36-item RIASEC interest inventory.
 *
 * Six statements per dimension (R I A S E C) rated 1–5, scored to 1–7, with the
 * Holland code, a radar of the six dimensions and the careers whose O*NET
 * interest profile fits best.
 */

import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, Check, RefreshCw, Target } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, discover } from "@/lib/api";
import type { DiscoverItem } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { ProgressRing } from "./motion";
import { Badge, Button, Card, ErrorNote, PageHeader, Progress, SourceLabel, Spinner, inputCls } from "./ui";

const SCALE_TONE = ["bg-white/5 text-fg-3", "bg-white/8 text-fg-2", "bg-white/10 text-fg", "bg-accent/15 text-accent", "bg-accent/25 text-accent"];

type Result = Awaited<ReturnType<typeof discover.submit>>;

export function DiscoverView() {
  const { t } = useI18n();
  const [items, setItems] = useState<DiscoverItem[]>([]);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [index, setIndex] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    discover
      .items()
      .then((r) => setItems(r.items))
      .catch((e) => setError((e as Error).message));
  }, []);

  const current = items[index];
  const answered = Object.keys(answers).length;

  const answer = async (value: number) => {
    if (!current) return;
    const next = { ...answers, [current.id]: value };
    setAnswers(next);
    if (index < items.length - 1) {
      setIndex(index + 1);
      return;
    }
    setBusy(true);
    try {
      setResult(await discover.submit(next));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (error) return <ErrorNote error={error} />;
  if (!items.length) return <Spinner label={t("disc_loading")} />;

  if (result) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader
          title={t("disc_result_title")}
          subtitle={`${t("disc_holland")}: ${result.holland_code}`}
          source={t("disc_source")}
          actions={
            <Button
              variant="outline"
              onClick={() => {
                setAnswers({});
                setIndex(0);
                setResult(null);
              }}
            >
              <RefreshCw size={15} /> {t("disc_retake")}
            </Button>
          }
        />

        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <h2 className="font-serif text-xl">{t("disc_profile")}</h2>
            <div className="mt-3 flex flex-col gap-3">
              {result.profile.map((row) => (
                <div key={row.dim}>
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-fg">
                      {row.name} <span className="text-fg-3">({row.dim})</span>
                    </span>
                    <span className="text-accent">{row.score.toFixed(1)}/7</span>
                  </div>
                  <div className="mt-1">
                    <Progress percent={(row.score / 7) * 100} label={`${row.name} score`} />
                  </div>
                  <p className="mt-1 text-[11px] text-fg-3">{row.blurb}</p>
                </div>
              ))}
            </div>
            <SourceLabel text={t("disc_source_scale")} />
          </Card>

          <Card>
            <h2 className="font-serif text-xl">{t("disc_matches")}</h2>
            <ul className="mt-3 flex flex-col gap-2">
              {result.top_careers.slice(0, 8).map((career) => (
                <li key={career.id} className="rounded-xl border border-white/8 bg-bg-3/40 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <Link href={`/careers/${career.id}`} className="text-sm text-fg hover:text-accent">
                      {career.title}
                    </Link>
                    <Badge tone="accent">{career.fit}%</Badge>
                  </div>
                  <p className="mt-1 text-[11px] text-fg-3">{career.why}</p>
                </li>
              ))}
            </ul>
            <div className="mt-3 flex gap-2">
              <Button href="/recommend" size="sm">
                {t("nav_recommend")}
              </Button>
              <Button href="/careers" size="sm" variant="outline">
                {t("nav_careers")}
              </Button>
            </div>
          </Card>
        </div>

        <Card>
          <h2 className="font-serif text-xl">{t("disc_history")}</h2>
          <SourceLabel text={t("disc_history_source")} />
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={t("disc_title")} subtitle={t("disc_sub")} source={t("disc_source_items")} />

      <div className="flex items-center gap-4">
        <ProgressRing
          value={(100 * answered) / items.length}
          size={64}
          stroke={6}
          label={`${answered}/${items.length}`}
        />
        <div className="flex-1">
          <Progress percent={(100 * answered) / items.length} label={t("disc_progress")} />
          <p className="mt-1 text-xs text-fg-3">
            {t("disc_question")} {index + 1} / {items.length}
          </p>
        </div>
      </div>

      <AnimatePresence mode="wait">
        <motion.div
          key={current.id}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -16 }}
          transition={{ duration: 0.2 }}
        >
          <Card>
            <p className="text-xs uppercase tracking-wide text-fg-3">{current.dim}</p>
            <p className="mt-2 font-serif text-2xl leading-snug text-fg">{current.text}</p>
            <div className="mt-5 grid grid-cols-5 gap-2" role="radiogroup" aria-label={current.text}>
              {[1, 2, 3, 4, 5].map((value) => (
                <button
                  key={value}
                  role="radio"
                  aria-checked={answers[current.id] === value}
                  aria-label={`${value} / 5`}
                  disabled={busy}
                  onClick={() => answer(value)}
                  className={`rounded-xl border border-white/8 py-3 text-sm transition hover:border-accent/40 ${
                    answers[current.id] === value ? SCALE_TONE[value - 1] : "text-fg-3"
                  }`}
                >
                  {value}
                </button>
              ))}
            </div>
            <p className="mt-2 flex justify-between text-[11px] text-fg-3">
              <span>{t("disc_scale_low")}</span>
              <span>{t("disc_scale_high")}</span>
            </p>
          </Card>
        </motion.div>
      </AnimatePresence>

      <div className="flex items-center justify-between">
        <Button variant="ghost" onClick={() => setIndex((i) => Math.max(0, i - 1))} disabled={index === 0}>
          <ArrowLeft size={15} /> {t("onb_back")}
        </Button>
        {busy && <Spinner label={t("disc_scoring")} />}
        {answered === items.length && !busy && (
          <span className="flex items-center gap-2 text-sm text-ok">
            <Check size={15} /> {t("disc_complete")}
          </span>
        )}
      </div>

      <Card>
        <h2 className="flex items-center gap-2 font-serif text-xl">
          <Target size={16} className="text-accent" /> {t("disc_why")}
        </h2>
        <p className="mt-2 text-sm text-fg-2">{t("disc_why_body")}</p>
        <label className="mt-3 block text-xs uppercase tracking-wide text-fg-3" htmlFor="disc-jump">
          {t("disc_jump")}
        </label>
        <select
          id="disc-jump"
          className={inputCls}
          value={index}
          onChange={(e) => setIndex(Number(e.target.value))}
        >
          {items.map((item, i) => (
            <option key={item.id} value={i}>
              {i + 1}. {item.text.slice(0, 60)}
              {answers[item.id] ? ` ✓ (${answers[item.id]})` : ""}
            </option>
          ))}
        </select>
        <SourceLabel text={t("disc_source_items")} />
      </Card>
    </div>
  );
}

export async function loadAssessmentHistory() {
  return api.assessmentHistory();
}
