"use client";

/**
 * Phase 8 share panel for /report/[runId] — loaded via next/dynamic from
 * the report view so its code never lands in the report route's
 * first-load bundle (same pattern as the Phase 7 chat panel).
 *
 * The raw share token is returned by the API exactly once, at creation;
 * at rest the server keeps only its SHA-256 hash. The panel therefore
 * shows the copyable link only for a link created in this session (kept
 * in sessionStorage so a same-session reload keeps copy + revoke), and
 * lists the owner's other links as metadata (expiry + status) with
 * revoke buttons — an older link can be revoked but never re-displayed.
 * Ownership is enforced server-side on every call; this panel only ever
 * renders what those calls return.
 */
import { useEffect, useState } from "react";
import { sharingApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { ShareCreated, ShareLink } from "@/lib/types";

type Created = { token: string; id: number; expires_at: string };

const EXPIRY_OPTIONS = [7, 14, 30];

export function SharePanel({ runId }: { runId: number }) {
  const { t, locale } = useI18n();
  const [shares, setShares] = useState<ShareLink[]>([]);
  const [created, setCreated] = useState<Created | null>(null);
  const [days, setDays] = useState(7);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(false);
  const [revokedNote, setRevokedNote] = useState(false);

  useEffect(() => {
    let cancelled = false;
    try {
      const raw = window.sessionStorage.getItem(`cg.share.${runId}`);
      if (raw) setCreated(JSON.parse(raw) as Created);
    } catch { /* private mode — link simply won't persist */ }
    sharingApi
      .list(runId)
      .then((res) => { if (!cancelled) setShares(res.shares); })
      .catch(() => { /* not the owner in this session — create will say so */ });
    return () => { cancelled = true; };
  }, [runId]);

  const fmtDate = (iso: string) =>
    new Date(iso).toLocaleDateString(locale === "en" ? "en-IN" : locale, {
      day: "numeric", month: "short", year: "numeric",
    });

  const create = async () => {
    setBusy(true); setError(false); setRevokedNote(false); setCopied(false);
    try {
      const res: ShareCreated = await sharingApi.create(runId, days);
      const fresh: Created = { token: res.token, id: res.id, expires_at: res.expires_at };
      setCreated(fresh);
      setShares((prev) => [res, ...prev.filter((s) => s.id !== res.id)]);
      try { window.sessionStorage.setItem(`cg.share.${runId}`, JSON.stringify(fresh)); } catch { /* ignore */ }
    } catch {
      setError(true);
    } finally { setBusy(false); }
  };

  const copy = async () => {
    if (!created) return;
    const url = `${window.location.origin}/shared/${created.token}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setCopied(false); // the readonly input below still allows manual copy
    }
  };

  const revoke = async (id: number) => {
    setError(false);
    try {
      const res = await sharingApi.revoke(runId, id);
      setShares((prev) => prev.map((s) => (s.id === id ? res.share : s)));
      if (created?.id === id) {
        setCreated(null);
        try { window.sessionStorage.removeItem(`cg.share.${runId}`); } catch { /* ignore */ }
      }
      setRevokedNote(true);
    } catch {
      setError(true);
    }
  };

  const others = shares.filter((s) => s.id !== created?.id);
  const shareUrl = created ? `${typeof window !== "undefined" ? window.location.origin : ""}/shared/${created.token}` : "";

  return (
    <section id="share" className="mt-8 scroll-mt-8 rounded-2xl border border-white/10 p-6" aria-label={t("p8_share_title")}>
      <h2 className="font-serif text-2xl">{t("p8_share_title")}</h2>
      <p className="mt-1 text-sm text-fg-2">{t("p8_share_sub")}</p>

      {created ? (
        <div className="mt-4 space-y-3">
          <div className="flex flex-col gap-2 sm:flex-row">
            <label className="sr-only" htmlFor="p8-share-url">{t("p8_share_title")}</label>
            <input
              id="p8-share-url"
              readOnly
              value={shareUrl}
              onFocus={(e) => e.target.select()}
              className="w-full rounded-xl border border-white/15 bg-transparent px-4 py-2 text-sm outline-none"
            />
            <button
              type="button"
              onClick={() => void copy()}
              className="shrink-0 rounded-xl bg-white px-4 py-2 text-sm font-medium text-black hover:bg-white/90"
            >
              {copied ? t("p8_share_copied") : t("p8_share_copy")}
            </button>
          </div>
          <p className="text-sm text-fg-2">{t("p8_share_active_until", { date: fmtDate(created.expires_at) })}</p>
          <p className="text-xs text-fg-3">{t("p8_share_copy_now")}</p>
          <button
            type="button"
            onClick={() => void revoke(created.id)}
            className="rounded-xl border border-white/15 px-4 py-2 text-sm font-medium hover:bg-white/5"
          >
            {t("p8_share_revoke")}
          </button>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="p8-share-days" className="text-sm text-fg-2">{t("p8_share_expiry_label")}</label>
            <select
              id="p8-share-days"
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="mt-1 block rounded-xl border border-white/15 bg-transparent px-3 py-2 text-sm outline-none"
            >
              {EXPIRY_OPTIONS.map((n) => (
                <option key={n} value={n} className="bg-bg-2">{t("p8_share_days", { n })}</option>
              ))}
            </select>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={() => void create()}
            className="rounded-xl bg-white px-4 py-2 text-sm font-medium text-black hover:bg-white/90 disabled:opacity-50"
          >
            {busy ? t("p8_share_creating") : t("p8_share_create")}
          </button>
        </div>
      )}

      {others.length > 0 && (
        <ul className="mt-4 space-y-2 border-t border-white/10 pt-4">
          {others.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="text-fg-2">
                {t("p8_share_active_until", { date: fmtDate(s.expires_at) })} · {s.status}
              </span>
              {s.status === "active" && (
                <button
                  type="button"
                  onClick={() => void revoke(s.id)}
                  className="rounded-lg border border-white/15 px-3 py-1 text-xs font-medium hover:bg-white/5"
                >
                  {t("p8_share_revoke")}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {revokedNote && <p className="mt-3 text-sm text-fg-2">{t("p8_share_revoked")}</p>}
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-300">{t("p8_share_error")}</p>
      )}
    </section>
  );
}
