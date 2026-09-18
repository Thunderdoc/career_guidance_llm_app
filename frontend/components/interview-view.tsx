"use client";

/**
 * `/interview` — a deterministic mock interview kit for a target career:
 * 10 behavioural + 10 technical questions with hints and STAR prompts.
 * The same seed always yields the same set, so practising twice is repeatable.
 */

import { useState } from "react";
import { ClipboardCheck, Mic, RefreshCw, Save } from "lucide-react";
import { api, pathway as pathwayApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useApi } from "@/lib/use-api";
import type { InterviewKit } from "@/lib/types";
import { AnimatedGroup, TextEffect } from "./motion";
import { Badge, Button, Card, Empty, Spinner } from "./ui";
import { CareerPicker } from "./career-picker";

export function InterviewView() {
  const { t } = useI18n();
  const signals = useApi(() => pathwayApi.signals(), []);
  const [careerId, setCareerId] = useState("");
  const [kit, setKit] = useState<InterviewKit | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);

  const target = signals.data?.target ?? null;
  const activeId = careerId || target?.career_id || "";

  async function load(seed?: number) {
    if (!activeId) return;
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      setKit(await api.interview(activeId, seed));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!kit) return;
    setBusy(true);
    try {
      await api.saveInterview({ career_id: kit.career_id, seconds: 0, notes });
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header>
        <TextEffect as="h1" className="font-serif text-3xl sm:text-4xl">
          {t("iv_title")}
        </TextEffect>
        <p className="mt-1 max-w-3xl text-sm text-fg-2">{t("iv_sub")}</p>
      </header>

      <Card className="flex flex-col gap-3">
        <label className="text-xs uppercase tracking-wide text-fg-3">{t("iv_pick")}</label>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[260px] flex-1">
            <CareerPicker
              value={careerId}
              label={target?.title ?? ""}
              placeholder={t("iv_pick_ph")}
              onChange={setCareerId}
            />
          </div>
          <Button variant="primary" onClick={() => void load()} disabled={busy || !activeId}>
            <Mic size={15} /> {kit ? t("iv_regenerate") : t("iv_start")}
          </Button>
          {kit && (
            <Button variant="outline" onClick={() => void load(Date.now() % 100000)} disabled={busy}>
              <RefreshCw size={15} /> {t("iv_shuffle")}
            </Button>
          )}
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
      </Card>

      {busy && <Spinner label={t("iv_loading")} />}

      {!busy && !kit && <Empty title={t("iv_empty")} hint={t("iv_sub")} />}

      {!busy && kit && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm text-fg-2">
              <Badge tone="accent">{kit.title}</Badge>
              <span className="text-xs text-fg-3">{t("iv_seed").replace("{n}", String(kit.seed))}</span>
            </div>
            <Button variant="outline" onClick={() => void save()} disabled={busy}>
              <Save size={15} /> {saved ? t("iv_saved_short") : t("iv_save")}
            </Button>
          </div>

          {(["behavioural", "technical"] as const).map((kind) => {
            const questions = kit.questions.filter((question) => question.kind === kind);
            return (
              <section key={kind}>
                <h2 className="font-serif text-2xl">
                  {kind === "behavioural" ? t("iv_behavioural") : t("iv_technical")}
                  <span className="ml-2 text-sm text-fg-3">
                    {t("iv_count").replace("{n}", String(questions.length))}
                  </span>
                </h2>
                <AnimatedGroup className="mt-3 flex flex-col gap-3">
                  {questions.map((question) => {
                    const open = openId === question.id;
                    return (
                      <Card key={question.id}>
                        <button
                          type="button"
                          onClick={() => setOpenId(open ? null : question.id)}
                          aria-expanded={open}
                          className="flex w-full items-start justify-between gap-3 text-left"
                        >
                          <span className="text-sm text-fg">{question.question}</span>
                          <ClipboardCheck size={16} className="mt-0.5 shrink-0 text-accent" />
                        </button>
                        {open && (
                          <div className="mt-3 border-t border-white/8 pt-3 text-sm">
                            <p className="text-fg-2">{question.hint}</p>
                            <div className="mt-2 grid gap-2 sm:grid-cols-2">
                              {(
                                [
                                  ["iv_situation", question.star.situation],
                                  ["iv_task", question.star.task],
                                  ["iv_action", question.star.action],
                                  ["iv_result", question.star.result],
                                ] as const
                              ).map(([label, value]) => (
                                <div key={label} className="rounded-xl border border-white/8 p-2.5">
                                  <p className="text-xs uppercase tracking-wide text-fg-3">{t(label)}</p>
                                  <p className="text-fg-2">{value}</p>
                                </div>
                              ))}
                            </div>
                            <label className="mt-3 block text-xs uppercase tracking-wide text-fg-3">
                              {t("iv_notes")}
                            </label>
                            <textarea
                              value={notes[question.id] ?? ""}
                              onChange={(event) =>
                                setNotes((prev) => ({ ...prev, [question.id]: event.target.value }))
                              }
                              rows={3}
                              className="mt-1 w-full rounded-xl border border-white/10 bg-bg-3/60 px-3 py-2 text-sm outline-none focus:border-accent/50"
                            />
                          </div>
                        )}
                      </Card>
                    );
                  })}
                </AnimatedGroup>
              </section>
            );
          })}
          <p className="text-xs text-fg-3">{kit.source}</p>
        </>
      )}
    </div>
  );
}
