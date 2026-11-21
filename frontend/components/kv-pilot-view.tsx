"use client";

/**
 * /pilot — pilot console (Kaam-Vaani Step 9.2).
 *
 * Plain and functional by design: the design agent owns the polish.
 * Coordinators + admins only (the API returns 403 for anyone else).
 * Pilot OPERATIONS supporting the AI's deployment — onboarding,
 * verification, metrics — never a recruiter portal.
 *
 * Metrics come only from stored rows. Voice-flow match views are not
 * persisted, so they are not shown here (L65).
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft,
  BarChart3,
  Check,
  Download,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  Upload,
  Users,
  X,
} from "lucide-react";
import {
  ApiError,
  api,
  apiUrl,
  type KvPilotBulkResponse,
  type KvPilotMetrics,
  type KvPilotReviewQueue,
  type KvPilotWorker,
} from "@/lib/api";
import { kvFlags } from "@/lib/flags";
import {
  KvCallout,
  KvEmptyState,
  KvHeader,
  KvSectionHeader,
  KvStat,
  KvStatusBadge,
  kvBtnDanger,
  kvBtnGhost,
  kvBtnPrimary,
  kvInputCls,
} from "./kv-portal-ui";

const BULK_EXAMPLE = `[{"phone": "+919876543210", "skills": ["electrical technician"], "education": "12th pass", "city": "Madurai"}, {"user_id": "u-worker-2", "skills": ["tailoring"], "city": "Dindigul"}]`;

function rateText(rate: number | null): string {
  if (rate === null) return "not reported yet";
  return `${Math.round(rate * 100)}%`;
}

export function KvPilotView() {
  const [metrics, setMetrics] = useState<KvPilotMetrics | null>(null);
  const [queue, setQueue] = useState<KvPilotReviewQueue | null>(null);
  const [workers, setWorkers] = useState<KvPilotWorker[]>([]);
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bulkText, setBulkText] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkResult, setBulkResult] = useState<KvPilotBulkResponse | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [acting, setActing] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [m, q, w] = await Promise.all([
        api.kvPilotMetrics(),
        api.kvPilotReviewQueue(),
        api.kvPilotWorkers(100, 0),
      ]);
      setMetrics(m);
      setQueue(q);
      setWorkers(w.workers);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
        setDenied(true);
      } else {
        setError(err instanceof Error ? err.message : "Could not load the console.");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function submitBulk() {
    setBulkError(null);
    setBulkResult(null);
    let rows: unknown;
    try {
      rows = JSON.parse(bulkText) as unknown;
    } catch {
      setBulkError("That is not valid JSON — paste a list of worker rows.");
      return;
    }
    if (!Array.isArray(rows) || rows.length === 0) {
      setBulkError("Paste a JSON list of at least one worker row.");
      return;
    }
    setBulkBusy(true);
    try {
      const result = await api.kvPilotBulkWorkers(rows as Record<string, unknown>[]);
      setBulkResult(result);
      void load();
    } catch (err) {
      setBulkError(err instanceof Error ? err.message : "Bulk onboarding failed.");
    } finally {
      setBulkBusy(false);
    }
  }

  async function act(kind: string, id: number, run: () => Promise<unknown>) {
    setActing(`${kind}:${id}`);
    try {
      await run();
      void load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "That action failed.");
    } finally {
      setActing(null);
    }
  }

  if (!kvFlags.pilot) {
    return (
      <KvEmptyState icon={BarChart3}>The pilot console is not enabled.</KvEmptyState>
    );
  }
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-fg-2">
        <Loader2 size={16} className="animate-spin" aria-hidden="true" /> Loading the console…
      </div>
    );
  }
  if (denied) {
    return (
      <KvCallout tone="danger">
        <p>
          <strong>Coordinators and admins only.</strong> The pilot console is for the people
          running the pilot. Sign in with a coordinator or admin account to use it.
        </p>
      </KvCallout>
    );
  }
  if (error && !metrics) {
    return (
      <KvCallout tone="danger">
        <p>
          <strong>Could not load the console.</strong> {error}
        </p>
      </KvCallout>
    );
  }

  return (
    <div className="space-y-8">
      <KvHeader>
        <Link href="/" className={kvBtnGhost}>
          <ArrowLeft size={15} aria-hidden="true" /> Home
        </Link>
        <h1 className="font-serif text-3xl">Pilot console</h1>
        <p className="text-sm text-fg-2">
          Pilot operations for Kaam-Vaani — onboarding, verification and metrics.
          Every number below comes from stored data.
        </p>
      </KvHeader>

      {error && (
        <KvCallout tone="danger">
          <p>
            <strong>Something failed.</strong> {error}
          </p>
        </KvCallout>
      )}

      {metrics && (
        <section className="space-y-3" aria-label="Pilot metrics">
          <KvSectionHeader icon={BarChart3} title="Metrics" />
          <div className="flex flex-wrap gap-2">
            <KvStat icon={Users} value={metrics.profiles.total} label="worker profiles" />
            <KvStat icon={ShieldCheck} value={metrics.consents.granted ?? 0} label="active consents" />
            <KvStat icon={Check} value={metrics.outcomes.hired ?? 0} label="hires reported" />
            <KvStat icon={BarChart3} value={rateText(metrics.retention.day30.rate)} label="day-30 retention" />
            <KvStat icon={BarChart3} value={rateText(metrics.retention.day90.rate)} label="day-90 retention" />
            <KvStat icon={ShieldAlert} value={metrics.scam_reports.open ?? 0} label="open scam reports" tone="danger" />
            <KvStat icon={Users} value={metrics.employers.pending ?? 0} label="employers awaiting review" />
            <KvStat icon={Users} value={metrics.listings.pending ?? 0} label="listings awaiting review" />
          </div>
          <p className="text-xs text-fg-2">
            Match views from the voice flow are not tracked — the stored match funnel is{" "}
            {metrics.shortlists.total} shortlists and {metrics.contact_requests.total} contact requests.
          </p>
          <div className="flex flex-wrap gap-3">
            <a className={kvBtnGhost} href={apiUrl("/api/v1/kv/pilot/metrics.csv")} download>
              <Download size={15} aria-hidden="true" /> Metrics CSV
            </a>
            <a className={kvBtnGhost} href={apiUrl("/api/v1/kv/pilot/workers.csv")} download>
              <Download size={15} aria-hidden="true" /> Workers CSV
            </a>
          </div>
        </section>
      )}

      <section className="space-y-3" aria-label="Bulk worker onboarding">
        <KvSectionHeader icon={Upload} title="Bulk worker onboarding" />
        <p className="text-sm text-fg-2">
          Paste a JSON list of worker rows (up to 100). Each row needs a{" "}
          <code>user_id</code> or a <code>phone</code> that matches an existing account, plus
          profile fields (skills, education, city, district, income_monthly, goal_type,
          interests, language). A bad row fails with its reason and never stops the batch.
        </p>
        <textarea
          className={kvInputCls}
          rows={5}
          value={bulkText}
          onChange={(e) => setBulkText(e.target.value)}
          placeholder={BULK_EXAMPLE}
          aria-label="Worker rows as JSON"
        />
        <div>
          <button type="button" className={kvBtnPrimary} onClick={() => void submitBulk()} disabled={bulkBusy || !bulkText.trim()}>
            {bulkBusy ? <Loader2 size={15} className="animate-spin" aria-hidden="true" /> : <Upload size={15} aria-hidden="true" />}
            Onboard workers
          </button>
        </div>
        {bulkError && (
          <KvCallout tone="danger">
            <p>
              <strong>Could not onboard.</strong> {bulkError}
            </p>
          </KvCallout>
        )}
        {bulkResult && (
          <div className="space-y-2">
            <p className="text-sm">
              Created {bulkResult.created}, updated {bulkResult.updated}, failed {bulkResult.failed}.
            </p>
            {bulkResult.results.filter((r) => r.status === "failed").length > 0 && (
              <ul className="space-y-1 text-sm">
                {bulkResult.results
                  .filter((r) => r.status === "failed")
                  .map((r) => (
                    <li key={r.row} className="text-danger">
                      Row {r.row + 1}: {r.error}
                    </li>
                  ))}
              </ul>
            )}
          </div>
        )}
      </section>

      {queue && (
        <section className="space-y-4" aria-label="Review queue">
          <KvSectionHeader
            icon={ShieldCheck}
            title="Review queue"
            count={(queue.counts.employers_pending ?? 0) + (queue.counts.listings_pending ?? 0) + (queue.counts.reports_open ?? 0)}
          />
          {queue.employers.length === 0 && queue.listings.length === 0 && queue.reports.length === 0 ? (
            <KvEmptyState icon={ShieldCheck}>Nothing waiting for review.</KvEmptyState>
          ) : (
            <>
              {queue.employers.map((employer) => (
                <div key={employer.id} className="flex flex-wrap items-center gap-3 rounded-xl bg-panel px-3 py-2 ring-1 ring-white/5">
                  <span className="text-sm font-semibold">{employer.business_name}</span>
                  <span className="text-xs text-fg-2">
                    {employer.contact_name} · {employer.city}
                  </span>
                  <KvStatusBadge status={employer.status} />
                  <span className="ml-auto flex gap-2">
                    <button
                      type="button"
                      className={kvBtnPrimary}
                      disabled={acting === `employer:${employer.id}`}
                      onClick={() => void act("employer", employer.id, () => api.kvPilotReviewEmployer(employer.id, { approve: true }))}
                    >
                      <Check size={15} aria-hidden="true" /> Approve
                    </button>
                    <button
                      type="button"
                      className={kvBtnDanger}
                      disabled={acting === `employer:${employer.id}`}
                      onClick={() => void act("employer", employer.id, () => api.kvPilotReviewEmployer(employer.id, { approve: false }))}
                    >
                      <X size={15} aria-hidden="true" /> Reject
                    </button>
                  </span>
                </div>
              ))}
              {queue.listings.map((listing) => (
                <div key={listing.id} className="flex flex-wrap items-center gap-3 rounded-xl bg-panel px-3 py-2 ring-1 ring-white/5">
                  <span className="text-sm font-semibold">{listing.title}</span>
                  <span className="text-xs text-fg-2">
                    {listing.city} · risk {listing.risk_score}
                  </span>
                  <KvStatusBadge status={listing.status} />
                  <span className="ml-auto flex gap-2">
                    <button
                      type="button"
                      className={kvBtnPrimary}
                      disabled={acting === `listing:${listing.id}`}
                      onClick={() => void act("listing", listing.id, () => api.kvPilotReviewListing(listing.id, { approve: true }))}
                    >
                      <Check size={15} aria-hidden="true" /> Approve
                    </button>
                    <button
                      type="button"
                      className={kvBtnDanger}
                      disabled={acting === `listing:${listing.id}`}
                      onClick={() => void act("listing", listing.id, () => api.kvPilotReviewListing(listing.id, { approve: false }))}
                    >
                      <X size={15} aria-hidden="true" /> Reject
                    </button>
                  </span>
                </div>
              ))}
              {queue.reports.map((report) => (
                <div key={report.id} className="flex flex-wrap items-center gap-3 rounded-xl bg-panel px-3 py-2 ring-1 ring-white/5">
                  <span className="text-sm font-semibold">Report #{report.id}</span>
                  <span className="text-xs text-fg-2">
                    listing {report.listing_id} · {report.reason}
                  </span>
                  <KvStatusBadge status={report.status} />
                  <span className="ml-auto flex gap-2">
                    <button
                      type="button"
                      className={kvBtnPrimary}
                      disabled={acting === `report:${report.id}`}
                      onClick={() => void act("report", report.id, () => api.kvPilotReviewReport(report.id, { action: "uphold" }))}
                    >
                      <Check size={15} aria-hidden="true" /> Uphold
                    </button>
                    <button
                      type="button"
                      className={kvBtnGhost}
                      disabled={acting === `report:${report.id}`}
                      onClick={() => void act("report", report.id, () => api.kvPilotReviewReport(report.id, { action: "dismiss" }))}
                    >
                      <X size={15} aria-hidden="true" /> Dismiss
                    </button>
                  </span>
                </div>
              ))}
            </>
          )}
        </section>
      )}

      <section className="space-y-3" aria-label="Worker roster">
        <KvSectionHeader icon={Users} title="Worker roster" count={workers.length} />
        {workers.length === 0 ? (
          <KvEmptyState icon={Users}>No worker profiles yet.</KvEmptyState>
        ) : (
          <ul className="space-y-1 text-sm">
            {workers.map((worker) => (
              <li key={worker.user_id} className="flex flex-wrap gap-2 rounded-xl bg-panel px-3 py-2 ring-1 ring-white/5">
                <span className="font-semibold">{worker.worker_name || worker.user_id}</span>
                <span className="text-fg-2">{worker.city || "—"}</span>
                <span className="text-fg-2">{(worker.skills || []).join(", ") || "no skills listed"}</span>
                {worker.is_sample && <span className="text-xs text-fg-2">sample data</span>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
