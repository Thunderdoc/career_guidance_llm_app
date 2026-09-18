"use client";

/** `/learn` — curated free courses, filterable, with save/done tracking + XP. */

import { BookOpen, CheckCircle2, ExternalLink, Filter, Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { learn } from "@/lib/api";
import type { LearnResource, XpStatus } from "@/lib/types";
import { useI18n } from "@/lib/i18n";
import { Badge, Button, Card, Empty, ErrorNote, PageHeader, SourceLabel, Spinner, Tabs, inputCls } from "./ui";

type Payload = Awaited<ReturnType<typeof learn.list>>;

export function LearnView() {
  const { t } = useI18n();
  const [data, setData] = useState<Payload | null>(null);
  const [tab, setTab] = useState<"all" | "saved" | "done">("all");
  const [query, setQuery] = useState("");
  const [skill, setSkill] = useState("");
  const [language, setLanguage] = useState("");
  const [level, setLevel] = useState("");
  const [freeOnly, setFreeOnly] = useState(false);
  const [saved, setSaved] = useState<LearnResource[]>([]);
  const [xp, setXp] = useState<XpStatus | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [payload, savedPayload] = await Promise.all([
        learn.list({ q: query, skill, language, level, free: freeOnly || undefined }),
        learn.saved(),
      ]);
      setData(payload);
      setSaved(savedPayload.results);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [query, skill, language, level, freeOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleSave = async (resource: LearnResource) => {
    try {
      if (resource.saved) await learn.unsave(resource.id);
      else await learn.save(resource.id);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const markDone = async (resource: LearnResource, done: boolean) => {
    try {
      const r = await learn.done(resource.id, done);
      setXp(r.xp);
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const rows = tab === "saved" ? saved : tab === "done" ? (data?.results ?? []).filter((r) => r.done) : (data?.results ?? []);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t("learn_title")}
        subtitle={t("learn_sub")}
        source={t("learn_source")}
        actions={
          xp && (
            <Badge tone="accent">
              {xp.xp} XP · {t("learn_done_count")} {xp.counts?.courses ?? 0}
            </Badge>
          )
        }
      />

      <Card className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-fg-3" />
            <input
              className={`${inputCls} pl-9`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("learn_search_ph")}
              aria-label={t("learn_search")}
            />
          </div>
          <select className={inputCls} value={skill} onChange={(e) => setSkill(e.target.value)} aria-label={t("learn_filter_skill")}>
            <option value="">{t("learn_filter_skill")}</option>
            {(data?.filters.skills ?? []).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select className={inputCls} value={level} onChange={(e) => setLevel(e.target.value)} aria-label={t("learn_filter_level")}>
            <option value="">{t("learn_filter_level")}</option>
            {(data?.filters.levels ?? []).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select
            className={inputCls}
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            aria-label={t("language")}
          >
            <option value="">{t("learn_filter_language")}</option>
            {(data?.filters.languages ?? []).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-xs text-fg-2">
            <input type="checkbox" checked={freeOnly} onChange={(e) => setFreeOnly(e.target.checked)} />
            {t("learn_free_only")}
          </label>
          <Button variant="ghost" size="sm" onClick={() => void load()}>
            <Filter size={14} /> {t("refresh")}
          </Button>
        </div>

        <Tabs
          tabs={[
            { id: "all", label: t("learn_tab_all"), count: data?.total ?? 0 },
            { id: "saved", label: t("learn_tab_saved"), count: saved.length },
            { id: "done", label: t("learn_tab_done"), count: xp?.counts?.courses ?? 0 },
          ]}
          value={tab}
          onChange={setTab}
        />
      </Card>

      {error && <ErrorNote error={error} retry={load} />}
      {loading && !data ? (
        <Spinner label={t("learn_loading")} />
      ) : rows.length === 0 ? (
        <Empty title={t("learn_empty_title")} hint={t("learn_empty_hint")} />
      ) : (
        <ol className="grid gap-3 sm:grid-cols-2">
          {rows.map((resource) => (
            <li key={resource.id} className="rounded-2xl border border-white/8 bg-bg-2/70 p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-fg" title={resource.title}>
                    {resource.title}
                  </p>
                  <p className="mt-0.5 text-[11px] text-fg-3">
                    {resource.provider} · {resource.skill} · {resource.level}
                    {resource.duration_minutes ? ` · ${resource.duration_minutes} min` : ""}
                  </p>
                </div>
                {resource.free && <Badge tone="ok">{t("learn_free")}</Badge>}
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                <a
                  href={resource.url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-accent hover:underline"
                >
                  <ExternalLink size={13} /> {t("learn_open")}
                </a>
                <button
                  onClick={() => void toggleSave(resource)}
                  className={`rounded-lg border px-2 py-1 ${resource.saved ? "border-accent/40 text-accent" : "border-white/12 text-fg-3 hover:text-fg"}`}
                  aria-pressed={Boolean(resource.saved)}
                >
                  {resource.saved ? t("learn_saved") : t("learn_save")}
                </button>
                <button
                  onClick={() => void markDone(resource, !resource.done)}
                  className={`flex items-center gap-1 rounded-lg border px-2 py-1 ${resource.done ? "border-ok/40 text-ok" : "border-white/12 text-fg-3 hover:text-fg"}`}
                  aria-pressed={Boolean(resource.done)}
                >
                  <CheckCircle2 size={13} /> {resource.done ? t("learn_done") : t("learn_mark_done")}
                </button>
              </div>
            </li>
          ))}
        </ol>
      )}

      <Card>
        <div className="flex items-center gap-2">
          <BookOpen size={16} className="text-accent" />
          <h2 className="font-serif text-xl">{t("learn_how_title")}</h2>
        </div>
        <p className="mt-2 text-sm text-fg-2">{t("learn_how_body")}</p>
        <SourceLabel text={t("learn_how_source")} />
      </Card>
    </div>
  );
}
