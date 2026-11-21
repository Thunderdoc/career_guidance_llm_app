"use client";

/**
 * Kaam-Vaani admin tab (Stage 5): the employer/listing/report review
 * queue. Admins approve or reject employers and listings, endorse
 * verified employers, and uphold or dismiss worker reports. Every
 * decision is audited server-side (users.audit + reviewed_by).
 *
 * English-only in Stage 5 (L37).
 */
import { useEffect, useState } from "react";
import { BadgeCheck, Briefcase, Building2, Check, Clock, Flag, Loader2, RefreshCw, ShieldAlert, X } from "lucide-react";
import { ApiError, api, type KvEmployer, type KvListing, type KvListingReport, type KvReviewQueue } from "@/lib/api";
import { cn } from "@/lib/cn";
import { kvCategoryForTitle } from "./kv-voice-ui";
import {
  KvCallout,
  KvEmptyState,
  KvRiskMeter,
  KvSampleChip,
  KvSectionHeader,
  KvSeverityChip,
  KvStat,
  KvStatusBadge,
  kvBtnDanger,
  kvBtnGhost,
  kvBtnPrimary,
  kvInputCls,
} from "./kv-portal-ui";

function ReviewButtons({ onReview, busy }: { onReview: (approve: boolean, note: string) => Promise<void>; busy: boolean }) {
  const [note, setNote] = useState("");
  const [confirmReject, setConfirmReject] = useState(false);
  return (
    <div className="mt-4 space-y-2 border-t border-white/10 pt-4">
      <input
        className={kvInputCls}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Review note (optional — shown to the employer)"
      />
      <div className="flex flex-wrap gap-2">
        <button type="button" className={kvBtnPrimary} disabled={busy} onClick={() => onReview(true, note)}>
          <Check size={15} /> Approve
        </button>
        {confirmReject ? (
          <>
            <button type="button" className={kvBtnDanger} disabled={busy} onClick={() => onReview(false, note)}>
              Confirm reject
            </button>
            <button type="button" className={kvBtnGhost} onClick={() => setConfirmReject(false)}>
              Keep
            </button>
          </>
        ) : (
          <button type="button" className={kvBtnDanger} onClick={() => setConfirmReject(true)}>
            <X size={15} /> Reject
          </button>
        )}
      </div>
    </div>
  );
}

export function KvAdminView() {
  const [queue, setQueue] = useState<KvReviewQueue | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<string>("");
  const [notice, setNotice] = useState("");
  const [endorseForm, setEndorseForm] = useState<Record<number, { by: string; type: string; note: string }>>({});

  async function load() {
    setLoading(true);
    setError("");
    try {
      setQueue(await api.kvReviewQueue());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the review queue.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function reviewEmployer(employer: KvEmployer, approve: boolean, note: string) {
    setBusyId(`employer-${employer.id}`);
    try {
      await api.kvReviewEmployer(employer.id, { approve, note });
      setNotice(`Employer "${employer.business_name}" ${approve ? "verified" : "rejected"}.`);
      await load();
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "Review failed.");
    } finally {
      setBusyId("");
    }
  }

  async function reviewListing(listing: KvListing, approve: boolean, note: string) {
    setBusyId(`listing-${listing.id}`);
    try {
      await api.kvReviewListing(listing.id, { approve, note });
      setNotice(`Listing "${listing.title}" ${approve ? "verified" : "rejected"}.`);
      await load();
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "Review failed.");
    } finally {
      setBusyId("");
    }
  }

  async function reviewReport(report: KvListingReport, action: "uphold" | "dismiss") {
    setBusyId(`report-${report.id}`);
    try {
      const res = await api.kvReviewReport(report.id, { action });
      setNotice(
        action === "uphold"
          ? `Report upheld — listing ${res.listing ? `is now ${res.listing.status}` : "already removed"}.`
          : "Report dismissed.",
      );
      await load();
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "Review failed.");
    } finally {
      setBusyId("");
    }
  }

  async function endorse(employer: KvEmployer) {
    const form = endorseForm[employer.id];
    if (!form || form.by.trim().length < 2) {
      setNotice("Enter who endorses this employer (e.g. the panchayat name).");
      return;
    }
    setBusyId(`endorse-${employer.id}`);
    try {
      await api.kvEndorseEmployer(employer.id, {
        endorsed_by: form.by,
        endorsed_by_type: form.type || "panchayat",
        note: form.note,
      });
      setNotice(`Employer "${employer.business_name}" endorsed by ${form.by}.`);
      await load();
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "Endorsement failed.");
    } finally {
      setBusyId("");
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[30vh] items-center justify-center" role="status">
        <Loader2 className="animate-spin text-fg-3" />
      </div>
    );
  }
  if (error || !queue) {
    return (
      <KvCallout tone="danger">
        <p className="text-sm">{error || "No queue data."}</p>
      </KvCallout>
    );
  }

  const { counts, employers, listings, reports } = queue;
  const openReports = reports.filter((r) => r.status === "open");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-serif text-2xl">Kaam-Vaani review queue</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            <KvStat icon={Building2} value={counts.employers_pending} label="employers waiting" tone="gold" />
            <KvStat icon={Briefcase} value={counts.listings_pending} label="listings waiting" tone="accent" />
            <KvStat icon={ShieldAlert} value={counts.listings_flagged} label="listings flagged" tone="danger" />
            <KvStat icon={Flag} value={counts.reports_open} label="open reports" tone="danger" />
          </div>
        </div>
        <button type="button" className={kvBtnGhost} onClick={load}>
          <RefreshCw size={15} /> Refresh
        </button>
      </div>
      {notice && (
        <KvCallout tone="info">
          <p className="text-sm">{notice}</p>
        </KvCallout>
      )}

      <section>
        <KvSectionHeader icon={Building2} title="Employers to review" count={employers.length} tone="gold" />
        {employers.length === 0 ? (
          <div className="mt-3">
            <KvEmptyState icon={Check}>Nothing waiting — all employers are reviewed.</KvEmptyState>
          </div>
        ) : (
          <ul className="mt-3 space-y-3">
            {employers.map((employer) => (
              <li key={employer.id} className="rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
                <div className="flex items-start gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gold/15 text-gold ring-1 ring-gold/30">
                    <Building2 size={22} aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-serif text-xl leading-snug">{employer.business_name}</p>
                    <p className="mt-1 text-sm text-fg-2">
                      {[employer.contact_name, employer.email, employer.phone_e164 || "no phone"]
                        .filter(Boolean)
                        .join(" · ")}
                      {employer.phone_verified ? " (verified)" : ""}
                    </p>
                    <p className="mt-1 text-sm text-fg-2">
                      {[employer.business_type, employer.city].filter(Boolean).join(" · ")}
                      {employer.district && employer.district !== employer.city ? `, ${employer.district}` : ""}
                    </p>
                  </div>
                  <KvStatusBadge status={employer.status} />
                </div>
                {employer.description && <p className="mt-3 text-sm text-fg-2">{employer.description}</p>}
                {employer.endorsed && (
                  <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-ok/10 px-2.5 py-1 text-xs font-medium text-ok ring-1 ring-ok/30">
                    <BadgeCheck size={13} aria-hidden="true" /> Endorsed by {employer.endorsed_by}
                  </p>
                )}
                <ReviewButtons
                  busy={busyId === `employer-${employer.id}`}
                  onReview={(approve, note) => reviewEmployer(employer, approve, note)}
                />
                {employer.status === "verified" && !employer.endorsed && (
                  <div className="mt-3 rounded-xl bg-white/[0.04] p-3 ring-1 ring-white/5">
                    <p className="flex items-center gap-2 text-sm font-medium">
                      <BadgeCheck size={15} aria-hidden="true" className="text-ok" /> Endorse this employer
                    </p>
                    <p className="mt-1 text-xs text-fg-3">
                      An endorsement means a trusted local body (panchayat, cooperative, ITI) vouches for this
                      employer. Workers see the badge.
                    </p>
                    <div className="mt-2 grid grid-cols-2 gap-3">
                      <input
                        className={kvInputCls}
                        placeholder="Endorsed by (e.g. Madurai Panchayat)"
                        value={endorseForm[employer.id]?.by ?? ""}
                        onChange={(e) =>
                          setEndorseForm((forms) => ({
                            ...forms,
                            [employer.id]: { ...(forms[employer.id] ?? { by: "", type: "panchayat", note: "" }), by: e.target.value },
                          }))
                        }
                      />
                      <select
                        className={kvInputCls}
                        value={endorseForm[employer.id]?.type ?? "panchayat"}
                        onChange={(e) =>
                          setEndorseForm((forms) => ({
                            ...forms,
                            [employer.id]: { ...(forms[employer.id] ?? { by: "", type: "panchayat", note: "" }), type: e.target.value },
                          }))
                        }
                      >
                        <option value="panchayat">Panchayat</option>
                        <option value="cooperative">Cooperative</option>
                        <option value="iti">ITI / training institute</option>
                        <option value="ngo">NGO</option>
                        <option value="other">Other</option>
                      </select>
                    </div>
                    <button
                      type="button"
                      className={`${kvBtnGhost} mt-2`}
                      disabled={busyId === `endorse-${employer.id}`}
                      onClick={() => endorse(employer)}
                    >
                      <BadgeCheck size={15} /> Endorse
                    </button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <KvSectionHeader icon={Briefcase} title="Listings to review" count={listings.length} />
        {listings.length === 0 ? (
          <div className="mt-3">
            <KvEmptyState icon={Check}>Nothing waiting — all listings are reviewed.</KvEmptyState>
          </div>
        ) : (
          <ul className="mt-3 space-y-3">
            {listings.map((listing) => {
              const cat = kvCategoryForTitle(listing.title);
              const CatIcon = cat.icon;
              return (
                <li key={listing.id} className="relative overflow-hidden rounded-[var(--radius-lg)] bg-panel p-5 pt-6 ring-1 ring-white/5">
                  <span aria-hidden="true" className={cn("absolute inset-x-0 top-0 h-1", cat.bar)} />
                  <div className="flex items-start gap-3">
                    <span
                      className={cn(
                        "flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ring-1",
                        cat.chip,
                      )}
                    >
                      <CatIcon size={22} aria-hidden="true" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="font-serif text-xl leading-snug">{listing.title}</p>
                      <p className="mt-1 text-sm text-fg-2">
                        {listing.city} · {listing.work_type}
                        {listing.pay_monthly_min != null || listing.pay_monthly_max != null
                          ? ` · ₹${(listing.pay_monthly_min ?? 0).toLocaleString("en-IN")}–₹${(listing.pay_monthly_max ?? 0).toLocaleString("en-IN")}/month`
                          : listing.pay_text
                            ? ` · ${listing.pay_text}`
                            : ""}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1.5">
                      <KvStatusBadge status={listing.status} />
                      {listing.is_sample && <KvSampleChip />}
                    </div>
                  </div>
                  <p className="mt-3 text-sm text-fg-2">{listing.description}</p>
                  {listing.risk_score > 0 && (
                    <div className="mt-3 rounded-xl border border-white/10 p-3">
                      <KvRiskMeter score={listing.risk_score} />
                      <ul className="mt-2 space-y-1.5">
                        {listing.risk_flags.map((flag) => (
                          <li key={flag.id} className="flex items-start justify-between gap-3 text-sm text-fg-2">
                            <span>{flag.message}</span>
                            <KvSeverityChip severity={flag.severity} />
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <ReviewButtons
                    busy={busyId === `listing-${listing.id}`}
                    onReview={(approve, note) => reviewListing(listing, approve, note)}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section>
        <KvSectionHeader icon={Flag} title="Worker reports" count={openReports.length} tone="coral" />
        {openReports.length === 0 ? (
          <div className="mt-3">
            <KvEmptyState icon={Flag}>No open reports.</KvEmptyState>
          </div>
        ) : (
          <ul className="mt-3 space-y-3">
            {openReports.map((report) => (
              <li key={report.id} className="rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
                <div className="flex items-start gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-kv-coral/15 text-kv-coral ring-1 ring-kv-coral/30">
                    <Flag size={22} aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">
                      Listing #{report.listing_id} — {report.reason.replaceAll("_", " ")}
                    </p>
                    {report.details && <p className="mt-1 text-sm text-fg-2">{report.details}</p>}
                    <p className="mt-1 flex items-center gap-1 text-xs text-fg-3">
                      <Clock size={12} aria-hidden="true" />
                      Reported {new Date(report.created_at).toLocaleString("en-IN")}
                    </p>
                  </div>
                  <KvStatusBadge status={report.status} />
                </div>
                <div className="mt-4 flex flex-wrap gap-2 border-t border-white/10 pt-4">
                  <button
                    type="button"
                    className={kvBtnDanger}
                    disabled={busyId === `report-${report.id}`}
                    onClick={() => reviewReport(report, "uphold")}
                  >
                    <Check size={15} /> Uphold — flag listing
                  </button>
                  <button
                    type="button"
                    className={kvBtnGhost}
                    disabled={busyId === `report-${report.id}`}
                    onClick={() => reviewReport(report, "dismiss")}
                  >
                    <X size={15} /> Dismiss
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
