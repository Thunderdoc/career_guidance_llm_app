"use client";

/**
 * /jobs — public verified job listings (Kaam-Vaani Stage 5).
 *
 * Guest-first: no sign-in needed to browse. Only admin-verified
 * listings appear here. Workers can report a listing (guests too);
 * three open reports auto-flag it for review. Sample data is
 * labelled wherever it appears.
 *
 * English-only in Stage 5 (L37); the voice flow stays the trilingual
 * surface.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, BadgeCheck, Briefcase, Clock, Flag, Loader2, MapPin, Search, Users, Wallet } from "lucide-react";
import { ApiError, api, type KvPublicListing } from "@/lib/api";
import { kvFlags } from "@/lib/flags";
import { cn } from "@/lib/cn";
import { kvCategoryForTitle } from "./kv-voice-ui";
import {
  KvCallout,
  KvEmptyState,
  KvHeader,
  KvSampleChip,
  kvBtnDanger,
  kvBtnGhost,
  kvBtnPrimary,
  kvInputCls,
  kvLinkAccent,
} from "./kv-portal-ui";

function formatPay(listing: KvPublicListing): string {
  if (listing.pay_text) return listing.pay_text;
  const min = listing.pay_monthly_min;
  const max = listing.pay_monthly_max;
  if (min == null && max == null) return "Pay not listed";
  const fmt = (n: number) => `₹${n.toLocaleString("en-IN")}`;
  if (min != null && max != null) return min === max ? `${fmt(min)}/month` : `${fmt(min)}–${fmt(max)}/month`;
  if (min != null) return `${fmt(min)}+/month`;
  return `Up to ${fmt(max as number)}/month`;
}

const REPORT_REASONS = [
  { value: "fee_demanded", label: "They asked me to pay a fee" },
  { value: "fake_job", label: "The job is not real" },
  { value: "wrong_pay", label: "The pay is wrong" },
  { value: "wrong_details", label: "The details are wrong" },
  { value: "other", label: "Something else" },
];

function ReportForm({ listing, onDone }: { listing: KvPublicListing; onDone: () => void }) {
  const [reason, setReason] = useState("fee_demanded");
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState(false);

  async function submit() {
    setBusy(true);
    setMessage("");
    try {
      const res = await api.kvReportListing(listing.id, { reason, details });
      setSent(true);
      setMessage(
        res.auto_flagged
          ? "Thank you — this listing has been flagged for review because several workers reported it."
          : "Thank you — your report is with the review team.",
      );
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Could not send the report — please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div className="mt-3">
        <KvCallout tone="ok">
          <p className="text-sm">{message}</p>
          <button type="button" className="mt-2 text-sm text-accent underline decoration-dotted" onClick={onDone}>
            Close
          </button>
        </KvCallout>
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-xl border border-danger/30 bg-danger/[0.06] p-4">
      <h4 className="flex items-center gap-2 text-sm font-medium">
        <Flag size={15} aria-hidden="true" className="text-danger" /> Report this job
      </h4>
      <label className="mt-3 block text-sm text-fg-2">
        What happened?
        <select className={kvInputCls} value={reason} onChange={(e) => setReason(e.target.value)}>
          {REPORT_REASONS.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </label>
      <label className="mt-3 block text-sm text-fg-2">
        Tell us more (optional)
        <textarea
          className={`${kvInputCls} min-h-[64px] resize-y`}
          value={details}
          onChange={(e) => setDetails(e.target.value)}
          placeholder="What did the employer say or do?"
        />
      </label>
      {message && <p className="mt-2 text-sm text-danger">{message}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className={kvBtnDanger} disabled={busy} onClick={submit}>
          {busy ? <Loader2 size={15} className="animate-spin" /> : null}
          Send report
        </button>
        <button type="button" className={kvBtnGhost} onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function ListingCard({ listing }: { listing: KvPublicListing }) {
  const [expanded, setExpanded] = useState(false);
  const [reporting, setReporting] = useState(false);
  // Category icon + colour from the job title (presentation only —
  // the same map the voice-flow match cards use).
  const cat = kvCategoryForTitle(listing.title);
  const CatIcon = cat.icon;

  return (
    <li className="relative overflow-hidden rounded-[var(--radius-lg)] bg-panel p-5 pt-6 ring-1 ring-white/5">
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
          <h3 className="font-serif text-xl leading-snug">{listing.title}</h3>
          <p className="mt-1 text-sm text-fg-2">{listing.employer_name}</p>
        </div>
        {listing.is_sample && <KvSampleChip />}
      </div>
      {listing.employer_endorsed && (
        <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-ok/10 px-2.5 py-1 text-xs font-medium text-ok ring-1 ring-ok/30">
          <BadgeCheck size={13} aria-hidden="true" /> Endorsed by {listing.employer_endorsed_by}
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-gold/10 px-2.5 py-1 text-xs font-semibold text-gold ring-1 ring-gold/30">
          <Wallet size={13} aria-hidden="true" /> {formatPay(listing)}
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-fg-2 ring-1 ring-white/10">
          <MapPin size={13} aria-hidden="true" /> {listing.city}
          {listing.district && listing.district !== listing.city ? `, ${listing.district}` : ""}
        </span>
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-fg-2 ring-1 ring-white/10">
          <Briefcase size={13} aria-hidden="true" /> {listing.work_type}
        </span>
        {listing.shift && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-fg-2 ring-1 ring-white/10">
            <Clock size={13} aria-hidden="true" /> {listing.shift}
          </span>
        )}
        {listing.openings > 1 && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-fg-2 ring-1 ring-white/10">
            <Users size={13} aria-hidden="true" /> {listing.openings} openings
          </span>
        )}
      </div>
      <p className="mt-3 line-clamp-3 text-sm text-fg-2">{listing.description}</p>
      {expanded && (
        <div className="mt-3 space-y-2 rounded-xl bg-white/[0.04] px-3 py-3 text-sm text-fg-2 ring-1 ring-white/5">
          {listing.requirements && (
            <p>
              <span className="text-fg">What you need: </span>
              {listing.requirements}
            </p>
          )}
          {listing.contact_info && (
            <p>
              <span className="text-fg">Contact: </span>
              {listing.contact_info}
            </p>
          )}
        </div>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" className={kvBtnGhost} onClick={() => setExpanded((v) => !v)}>
          {expanded ? "Show less" : "Show details"}
        </button>
        {kvFlags.consent && (
          <Link href={`/sharing?listing=${listing.id}`} className={kvBtnPrimary}>
            Share my profile
          </Link>
        )}
        <button type="button" className={kvBtnGhost} onClick={() => setReporting((v) => !v)}>
          <Flag size={15} /> Report this job
        </button>
      </div>
      {reporting && <ReportForm listing={listing} onDone={() => setReporting(false)} />}
    </li>
  );
}

export function JobsView() {
  const [listings, setListings] = useState<KvPublicListing[]>([]);
  const [sampleData, setSampleData] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [city, setCity] = useState("");
  const [cityQuery, setCityQuery] = useState("");
  const [category, setCategory] = useState("");

  async function load(cityFilter: string, categoryFilter: string) {
    setLoading(true);
    setError("");
    try {
      const res = await api.kvPublicListings({
        city: cityFilter || undefined,
        role_category: categoryFilter || undefined,
        limit: 100,
      });
      setListings(res.listings);
      setSampleData(res.sample_data);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load jobs.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load("", "");
  }, []);

  function applyFilters() {
    load(city, category);
  }

  if (!kvFlags.employers) {
    return (
      <main className="mx-auto w-full max-w-2xl px-5 pb-20">
        <KvHeader />
        <p className="mt-6 rounded-xl border border-white/15 px-4 py-3 text-sm text-fg-2">
          Job listings are not enabled on this deployment.
        </p>
      </main>
    );
  }

  const categories = Array.from(new Set(listings.map((l) => l.role_category).filter(Boolean))).sort();

  return (
    <main className="mx-auto w-full max-w-2xl px-5 pb-20">
      <KvHeader>
        {kvFlags.consent && (
          <Link href="/sharing" className={kvLinkAccent}>
            My sharing
          </Link>
        )}
        <Link href="/employers" className={kvLinkAccent}>
          For employers
        </Link>
      </KvHeader>
      <div className="flex items-center gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-accent/15 text-accent ring-1 ring-accent/30">
          <BadgeCheck size={22} aria-hidden="true" />
        </span>
        <h1 className="font-serif text-3xl">Verified jobs</h1>
      </div>
      <p className="mt-2 text-sm text-fg-2">
        Jobs from businesses an admin has reviewed. If a job asks you to pay a fee or share an OTP, report it — it is
        almost certainly a scam.
      </p>
      {sampleData && (
        <p className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          These listings are sample data for the Kaam-Vaani demo — they are not real jobs. Real listings will appear
          here once the pilot starts.
        </p>
      )}

      <div className="mt-6 flex flex-wrap items-end gap-3 rounded-2xl bg-panel p-4 ring-1 ring-white/5">
        <label className="min-w-[160px] flex-1 text-sm text-fg-2">
          City
          <input
            className={kvInputCls}
            value={city}
            onChange={(e) => setCity(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && applyFilters()}
            placeholder="e.g. Madurai"
          />
        </label>
        <label className="min-w-[160px] flex-1 text-sm text-fg-2">
          Kind of work
          <select className={kvInputCls} value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All kinds</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className={kvBtnPrimary}
          onClick={() => {
            setCityQuery(city);
            applyFilters();
          }}
        >
          <Search size={15} /> Search
        </button>
      </div>

      <div className="mt-6" aria-live="polite">
        {loading ? (
          <div className="flex min-h-[30vh] items-center justify-center" role="status">
            <Loader2 className="animate-spin text-fg-3" />
          </div>
        ) : error ? (
          <KvCallout tone="danger">
            <p className="text-sm">{error}</p>
          </KvCallout>
        ) : listings.length === 0 ? (
          <KvEmptyState icon={Search}>
            {cityQuery ? `No verified jobs in "${cityQuery}" yet.` : "No verified jobs yet."} Check back soon — or try
            the voice guide to see what fits you.
          </KvEmptyState>
        ) : (
          <>
            <p className="flex items-center gap-2 text-sm text-fg-2">
              <Briefcase size={15} aria-hidden="true" className="text-accent" />
              <span>
                {listings.length} verified {listings.length === 1 ? "job" : "jobs"}
                {cityQuery ? ` in "${cityQuery}"` : ""}
              </span>
            </p>
            <ul className="mt-4 space-y-3">
              {listings.map((listing) => (
                <ListingCard key={listing.id} listing={listing} />
              ))}
            </ul>
          </>
        )}
      </div>
      <Link href="/" className="mt-8 inline-flex items-center gap-1 text-xs text-fg-3 hover:text-fg">
        <ArrowLeft size={14} /> Back to app
      </Link>
    </main>
  );
}
