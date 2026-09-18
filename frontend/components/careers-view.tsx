"use client";

/**
 * `/careers` — browse the 974-occupation catalogue.
 * Filters: free-text, industry family, preparation zone, remote only.
 * Every card shows pay, demand and the tools the role actually uses, each with
 * the curated market source.
 */

import { useEffect, useMemo, useState } from "react";
import { ArrowRight, MapPin, Search, Wifi } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { TextEffect } from "./motion";
import { Badge, Button, Card, Empty, ErrorNote, Spinner } from "./ui";

type Row = {
  id: string;
  title: string;
  family: string;
  family_label?: string;
  job_zone: number;
  salary_p50: number | null;
  currency_symbol?: string;
  demand_label?: string;
  remote: boolean;
  indian_titles?: string[];
  top_skills?: string[];
  technology?: string[];
};

const PAGE = 24;

export function CareersView() {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [family, setFamily] = useState("");
  const [zone, setZone] = useState<number | "">("");
  const [remote, setRemote] = useState(false);
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState<{ families: { id: string; label: string }[]; zones: number[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const params = useMemo(
    () => ({
      q: query.trim(),
      family,
      job_zone: zone === "" ? undefined : Number(zone),
      limit: PAGE,
      offset,
    }),
    [query, family, zone, offset],
  );

  useEffect(() => {
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const payload = await api.careers(params);
        setRows(payload.results as Row[]);
        setTotal(payload.total);
        setFilters(payload.filters ?? null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    }, 200);
    return () => window.clearTimeout(timer);
  }, [params]);

  const visible = remote ? rows.filter((row) => row.remote) : rows;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <TextEffect as="h1" className="font-serif text-3xl sm:text-4xl">
          {t("cr_title")}
        </TextEffect>
        <p className="mt-1 text-sm text-fg-2">{t("cr_sub").replace("{total}", String(total || 974))}</p>
      </header>

      <Card className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[220px] flex-1">
            <label className="mb-1.5 block text-xs uppercase tracking-wide text-fg-3">{t("cr_search")}</label>
            <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-bg-3/60 px-3 py-2 focus-within:border-accent/50">
              <Search size={15} className="text-fg-3" />
              <input
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setOffset(0);
                }}
                className="w-full bg-transparent text-sm outline-none placeholder:text-fg-3"
                placeholder={t("cr_search")}
              />
            </div>
          </div>
          <div>
            <label className="mb-1.5 block text-xs uppercase tracking-wide text-fg-3">{t("cr_family")}</label>
            <select
              value={family}
              onChange={(event) => {
                setFamily(event.target.value);
                setOffset(0);
              }}
              className="rounded-xl border border-white/10 bg-bg-3/60 px-3 py-2 text-sm text-fg outline-none"
            >
              <option value="">{t("cr_all")}</option>
              {(filters?.families ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1.5 block text-xs uppercase tracking-wide text-fg-3">{t("cr_zone")}</label>
            <select
              value={String(zone)}
              onChange={(event) => {
                setZone(event.target.value === "" ? "" : Number(event.target.value));
                setOffset(0);
              }}
              className="rounded-xl border border-white/10 bg-bg-3/60 px-3 py-2 text-sm text-fg outline-none"
            >
              <option value="">{t("cr_all")}</option>
              {(filters?.zones ?? [1, 2, 3, 4, 5]).map((value) => (
                <option key={value} value={value}>
                  {t("cr_zone_n").replace("{n}", String(value))}
                </option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2 pb-2 text-sm text-fg-2">
            <input
              type="checkbox"
              checked={remote}
              onChange={(event) => setRemote(event.target.checked)}
              className="accent-[var(--accent)]"
            />
            <Wifi size={14} /> {t("cr_remote")}
          </label>
        </div>
      </Card>

      {error && <ErrorNote error={error} />}
      {loading && <Spinner label={t("cr_loading")} />}

      {!loading && visible.length === 0 && <Empty title={t("cr_empty")} hint={t("cr_search")} />}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {visible.map((row) => (
          <Card key={row.id}>
            <div className="flex items-start justify-between gap-2">
              <Link href={`/careers/${row.id}`} className="font-medium text-fg hover:text-accent">
                {row.title}
              </Link>
              <Badge tone="muted">{t("cr_zone_n").replace("{n}", String(row.job_zone))}</Badge>
            </div>
            {row.indian_titles && row.indian_titles.length > 0 && (
              <p className="mt-1 text-xs text-fg-3">{row.indian_titles.slice(0, 2).join(" · ")}</p>
            )}
            <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
              <div>
                <p className="text-xs uppercase tracking-wide text-fg-3">{t("cr_salary")}</p>
                <p className="text-fg">
                  {row.salary_p50 === null || row.salary_p50 === undefined
                    ? "—"
                    : `${row.currency_symbol ?? "₹"}${row.salary_p50.toLocaleString("en-IN")}`}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-fg-3">{t("cr_demand")}</p>
                <p className="text-fg">{row.demand_label ?? "—"}</p>
              </div>
            </div>
            {(row.top_skills ?? row.technology ?? []).length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {(row.top_skills ?? row.technology ?? []).slice(0, 4).map((skill) => (
                  <Badge key={skill}>{skill}</Badge>
                ))}
              </div>
            )}
            <div className="mt-3 flex items-center justify-between">
              {row.remote && (
                <span className="flex items-center gap-1 text-xs text-fg-3">
                  <MapPin size={12} /> {t("cr_remote")}
                </span>
              )}
              <Link
                href={`/careers/${row.id}`}
                className="ml-auto inline-flex items-center gap-1 text-xs text-accent hover:underline"
              >
                {t("cr_open")} <ArrowRight size={12} />
              </Link>
            </div>
          </Card>
        ))}
      </div>

      {offset + PAGE < total && (
        <div className="flex justify-center">
          <Button variant="outline" onClick={() => setOffset(offset + PAGE)} disabled={loading}>
            {t("cr_more")}
          </Button>
        </div>
      )}
      <p className="text-xs text-fg-3">{t("cr_source")}</p>
    </div>
  );
}
