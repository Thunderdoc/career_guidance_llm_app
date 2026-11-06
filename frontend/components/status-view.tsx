"use client";

/**
 * /status (Phase 10): a plain status page that checks the API LIVE from
 * the visitor's browser — GET /api/v1/health (liveness) and
 * GET /api/v1/ready (readiness: database + catalogue). Nothing is
 * cached or pre-rendered: each row shows checking → ok / down from the
 * actual response (a 503 from /ready is a real "not ready" answer, not
 * an error in this page). Localised EN/TA/HI via the p10_status_* keys.
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type RowState = "checking" | "ok" | "down";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export function StatusView() {
  const { t } = useI18n();
  const [live, setLive] = useState<RowState>("checking");
  const [ready, setReady] = useState<RowState>("checking");
  const [version, setVersion] = useState("");
  const [occupations, setOccupations] = useState<number | null>(null);

  const check = useCallback(async () => {
    setLive("checking");
    setReady("checking");
    try {
      const health = await api.health();
      setLive(health.status === "ok" ? "ok" : "down");
      setVersion(health.version);
      setOccupations(health.occupations);
    } catch {
      setLive("down");
    }
    try {
      const resp = await fetch(`${BASE}/api/v1/ready`);
      const body = (await resp.json()) as { status?: string };
      setReady(resp.ok && body.status === "ready" ? "ok" : "down");
    } catch {
      setReady("down");
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  const badge = (state: RowState) =>
    state === "checking" ? (
      <span className="text-fg-2">{t("p10_status_checking")}</span>
    ) : state === "ok" ? (
      <span className="font-semibold text-[var(--cg-success)]">{t("p10_status_ok")}</span>
    ) : (
      <span className="font-semibold text-[var(--cg-danger)]">{t("p10_status_down")}</span>
    );

  return (
    <main className="mx-auto w-full max-w-xl px-5 py-16">
      <h1 className="font-serif text-3xl">{t("p10_status_title")}</h1>
      <p className="mt-3 text-sm leading-relaxed text-fg-2">{t("p10_status_sub")}</p>
      <dl className="mt-8 space-y-4">
        <div className="flex items-center justify-between rounded-2xl border border-white/10 p-5">
          <dt className="text-sm font-medium">{t("p10_status_live")}</dt>
          <dd>{badge(live)}</dd>
        </div>
        <div className="flex items-center justify-between rounded-2xl border border-white/10 p-5">
          <dt className="text-sm font-medium">{t("p10_status_ready")}</dt>
          <dd>{badge(ready)}</dd>
        </div>
        {version && (
          <div className="flex items-center justify-between rounded-2xl border border-white/10 p-5">
            <dt className="text-sm font-medium">{t("p10_status_version")}</dt>
            <dd className="text-sm text-fg-2">{version}</dd>
          </div>
        )}
        {occupations !== null && (
          <div className="flex items-center justify-between rounded-2xl border border-white/10 p-5">
            <dt className="text-sm font-medium">{t("p10_status_occupations")}</dt>
            <dd className="text-sm text-fg-2">{occupations}</dd>
          </div>
        )}
      </dl>
      <button
        type="button"
        onClick={() => void check()}
        className="mt-8 rounded-xl bg-white px-5 py-3 text-sm font-medium text-black hover:bg-white/90"
      >
        {t("p10_status_recheck")}
      </button>
    </main>
  );
}
