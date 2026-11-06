"use client";

/**
 * Phase 3 — Proof of skill, inside /account:
 * take a verification quiz (answers are graded server-side; the key is
 * never shipped), submit project evidence (self-reported until reviewed),
 * and control the public profile (/p/[handle]).
 */

import { useState } from "react";
import { BadgeCheck, ExternalLink, ShieldCheck } from "lucide-react";
import { verifyApi, type QuizAttempt, type QuizResult } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useI18n, type Key } from "@/lib/i18n";
import { useApi } from "@/lib/use-api";
import { Badge, Button, Card, Empty, ErrorNote, Field, Spinner, inputCls } from "./ui";

type TFn = (k: Key, vars?: Record<string, string | number>) => string;

function statusBadge(status: string, t: TFn) {
  if (status === "verified") return <Badge tone="ok">{t("p3_status_verified")}</Badge>;
  if (status === "project_submitted") return <Badge tone="gold">{t("p3_status_submitted")}</Badge>;
  return <Badge tone="muted">{t("p3_status_unverified")}</Badge>;
}

export function VerifyView() {
  const { t } = useI18n();
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi(() => verifyApi.mine(), []);
  const [attempt, setAttempt] = useState<QuizAttempt | null>(null);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [result, setResult] = useState<QuizResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  // public-profile controls
  const [handle, setHandle] = useState(user?.handle ?? "");
  const [enabled, setEnabled] = useState(user?.public_profile ?? false);
  const [minor, setMinor] = useState(user?.is_minor ?? false);
  const [savedNote, setSavedNote] = useState("");

  // project form
  const [pSkill, setPSkill] = useState("python");
  const [pTitle, setPTitle] = useState("");
  const [pLink, setPLink] = useState("");
  const [pDesc, setPDesc] = useState("");
  const [pChecklist, setPChecklist] = useState("");

  if (loading && !data) return <Spinner label={t("p3_verify_title")} />;
  if (error) return <ErrorNote error={error} retry={reload} />;
  if (!data) return null;

  const bySkill = new Map(data.verifications.map((v) => [v.skill, v]));

  async function startQuiz(skill: string) {
    setBusy(true);
    setActionError("");
    setResult(null);
    setAnswers({});
    try {
      setAttempt(await verifyApi.startQuiz(skill));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submitQuiz() {
    if (!attempt) return;
    setBusy(true);
    setActionError("");
    try {
      const out = await verifyApi.submitQuiz(attempt.skill, attempt.attempt_token, answers);
      setResult(out.result);
      setAttempt(null);
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function submitProject() {
    setBusy(true);
    setActionError("");
    try {
      await verifyApi.submitProject(pSkill, {
        title: pTitle,
        link: pLink,
        description: pDesc,
        checklist: pChecklist.split("\n").map((s) => s.trim()).filter(Boolean),
      });
      setPTitle("");
      setPLink("");
      setPDesc("");
      setPChecklist("");
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveProfile() {
    setBusy(true);
    setActionError("");
    setSavedNote("");
    try {
      await verifyApi.setPublicProfile({ handle, public_profile: enabled, is_minor: minor });
      setSavedNote(t("p3_saved"));
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h2 className="flex items-center gap-2 font-serif text-2xl">
          <ShieldCheck size={20} className="text-accent" /> {t("p3_verify_title")}
        </h2>
        <p className="mt-1 text-sm text-fg-2">{t("p3_verify_sub")}</p>
      </header>

      {actionError && <ErrorNote error={actionError} />}

      {result && (
        <Card className={result.passed ? "border-emerald-400/30" : "border-gold/30"}>
          <p className="text-sm text-fg">
            {t("p3_your_score")}: <strong>{result.score_percent}%</strong> ({result.correct}/{result.total})
          </p>
          <p className="mt-1 text-sm text-fg-2">
            {result.passed ? t("p3_quiz_passed") : t("p3_quiz_failed", { score: result.score_percent })}
          </p>
          <ul className="mt-3 flex flex-col gap-1 text-xs text-fg-3">
            {result.detail.map((d) => (
              <li key={d.id}>
                {d.correct ? "✓" : "✗"} {d.explanation}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {data.quizzes.map((quiz) => {
          const state = bySkill.get(quiz.skill);
          const active = attempt?.skill === quiz.skill;
          return (
            <Card key={quiz.skill}>
              <div className="flex items-center justify-between gap-2">
                <h3 className="font-serif text-lg">{quiz.title}</h3>
                {state ? statusBadge(state.status, t) : statusBadge("unverified", t)}
              </div>
              <p className="mt-1 text-xs text-fg-3">
                {t("p3_quiz_meta", { count: quiz.questions, pass: 70 })}
                {state?.best_score != null ? ` · ${t("p3_your_score")}: ${state.best_score}%` : ""}
                {state?.self_reported ? ` · ${t("p3_self_reported")}` : ""}
              </p>
              {!active && (
                <Button size="sm" className="mt-3" disabled={busy} onClick={() => startQuiz(quiz.skill)}>
                  {t("p3_take_quiz")}
                </Button>
              )}
              {active && attempt && (
                <div className="mt-3 flex flex-col gap-4">
                  {attempt.questions.map((q, qi) => (
                    <fieldset key={q.id}>
                      <legend className="text-sm text-fg">
                        {qi + 1}. {q.question}
                      </legend>
                      <div className="mt-1 flex flex-col gap-1">
                        {q.options.map((option, oi) => (
                          <label key={oi} className="flex cursor-pointer items-center gap-2 text-sm text-fg-2">
                            <input
                              type="radio"
                              name={q.id}
                              checked={answers[q.id] === oi}
                              onChange={() => setAnswers((a) => ({ ...a, [q.id]: oi }))}
                            />
                            {option}
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  ))}
                  <Button size="sm" disabled={busy} onClick={submitQuiz}>
                    {t("p3_submit_answers")}
                  </Button>
                </div>
              )}
            </Card>
          );
        })}
      </div>

      <Card>
        <h3 className="font-serif text-lg">{t("p3_project_title")}</h3>
        <p className="mt-1 text-xs text-fg-3">{t("p3_project_note")}</p>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <Field label={t("p3_project_name")}>
            <input className={inputCls} value={pTitle} onChange={(e) => setPTitle(e.target.value)} />
          </Field>
          <Field label={t("p3_project_link")}>
            <input className={inputCls} value={pLink} onChange={(e) => setPLink(e.target.value)} />
          </Field>
          <Field label={t("p3_skill_label")}>
            <select className={inputCls} value={pSkill} onChange={(e) => setPSkill(e.target.value)}>
              {data.quizzes.map((q) => (
                <option key={q.skill} value={q.skill}>
                  {q.title}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t("p3_project_desc")}>
            <input className={inputCls} value={pDesc} onChange={(e) => setPDesc(e.target.value)} />
          </Field>
        </div>
        <div className="mt-3">
          <Field label={t("p3_project_checklist")}>
            <textarea
              className={inputCls}
              rows={3}
              value={pChecklist}
              onChange={(e) => setPChecklist(e.target.value)}
            />
          </Field>
        </div>
        <Button size="sm" className="mt-3" disabled={busy || pTitle.length < 3} onClick={submitProject}>
          {t("p3_project_submit")}
        </Button>
        {data.verifications.flatMap((v) => v.projects).length > 0 && (
          <ul className="mt-4 flex flex-col gap-2 text-sm">
            {data.verifications.flatMap((v) =>
              v.projects.map((p) => (
                <li key={p.id} className="flex flex-wrap items-center gap-2 rounded-xl border border-white/8 p-2">
                  <a href={p.link} target="_blank" rel="noreferrer" className="text-accent hover:underline">
                    {p.title} <ExternalLink size={12} className="inline" />
                  </a>
                  <Badge tone="muted">{p.skill}</Badge>
                  {p.self_reported && <Badge tone="gold">{t("p3_self_reported")}</Badge>}
                </li>
              )),
            )}
          </ul>
        )}
      </Card>

      <Card>
        <h3 className="flex items-center gap-2 font-serif text-lg">
          <BadgeCheck size={18} className="text-accent" /> {t("p3_public_title")}
        </h3>
        <p className="mt-1 text-xs text-fg-3">{t("p3_public_sub")}</p>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <Field label={t("p3_handle")}>
            <input
              className={inputCls}
              value={handle}
              onChange={(e) => setHandle(e.target.value.toLowerCase())}
              placeholder="your-handle"
            />
          </Field>
          <div className="flex flex-col justify-end gap-2 text-sm text-fg-2">
            <label className="flex cursor-pointer items-center gap-2">
              <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
              {t("p3_public_enable")}
            </label>
            <label className="flex cursor-pointer items-center gap-2">
              <input type="checkbox" checked={minor} onChange={(e) => setMinor(e.target.checked)} />
              {t("p3_minor")}
            </label>
          </div>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button size="sm" disabled={busy} onClick={saveProfile}>
            {t("p3_save")}
          </Button>
          {savedNote && <span className="text-xs text-fg-3">{savedNote}</span>}
          {enabled && handle && !minor && (
            <a href={`/p/${handle}`} className="text-xs text-accent hover:underline">
              {t("p3_view_profile")}
            </a>
          )}
        </div>
      </Card>

      {data.verifications.length === 0 && (
        <Empty title={t("p3_status_unverified")} hint={t("p3_verify_sub")} />
      )}
    </div>
  );
}
