"use client";

/**
 * Employer matching (Kaam-Vaani Stage 6) — plain and functional by
 * design; the design agent owns the polish.
 *
 * Rendered only for VERIFIED employers (the dashboard gates it) and
 * only when the KV_CONSENT flag is on. Candidates are ranked workers
 * who consented to THIS employer; each candidate carries only the
 * fields they consented to share — the server filters, never the UI.
 * Shortlist, contact requests and hire-outcome reporting live here.
 * English-only in Stage 6 (L37).
 */
import { useEffect, useState } from "react";
import {
  BookOpen,
  CalendarCheck,
  Check,
  Clock,
  Loader2,
  Search,
  Star,
  TrendingUp,
  User,
  Users,
} from "lucide-react";
import {
  ApiError,
  api,
  type KvCandidate,
  type KvCandidateReason,
  type KvListing,
  type KvOutcomeSummary,
  type KvShortlistEntry,
} from "@/lib/api";
import { cn } from "@/lib/cn";
import { KvMatchMeter } from "./kv-voice-ui";
import {
  KvCallout,
  KvComponentBar,
  KvEmptyState,
  KvSampleChip,
  KvSectionHeader,
  KvStat,
  KvStatusBadge,
  kvBtnGhost,
  kvBtnPrimary,
  kvInputCls,
} from "./kv-portal-ui";
const OUTCOMES = [
  { value: "hired", label: "Hired" },
  { value: "interviewed", label: "Interviewed" },
  { value: "not_hired", label: "Not hired" },
] as const;

function fmtDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-IN");
}

/** One line per structured reason from the candidate scorer. */
function reasonText(r: KvCandidateReason): string {
  switch (r.kind) {
    case "skill":
      return `Has: ${(r.skills ?? []).join(", ")}`;
    case "title":
      return "Job title matches their skills";
    case "city":
      return `Lives in ${r.city ?? "the same city"}`;
    case "district":
      return `Lives in ${r.district ?? "the same district"} district`;
    case "income":
      return "Pay fits what they need";
    case "no_requirements":
      return "This job lists no required skills";
    default:
      return "";
  }
}

function pct(x: number): string {
  return `${Math.round(x * 100)}%`;
}

function CandidateCard({
  candidate,
  listingId,
  shortlisted,
  onChanged,
}: {
  candidate: KvCandidate;
  listingId: number;
  shortlisted: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [showContact, setShowContact] = useState(false);
  const [contactText, setContactText] = useState("");
  const [showOutcome, setShowOutcome] = useState(false);
  const [outcome, setOutcome] = useState<"hired" | "interviewed" | "not_hired">("hired");
  const [note, setNote] = useState("");
  const p = candidate.profile;

  async function shortlist() {
    setBusy(true);
    setMessage("");
    try {
      await api.kvShortlistAdd({ listing_id: listingId, worker_user_id: candidate.worker_user_id });
      setMessage("Shortlisted.");
      onChanged();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Could not shortlist.");
    } finally {
      setBusy(false);
    }
  }

  async function contact() {
    setBusy(true);
    setMessage("");
    try {
      await api.kvContactRequestSend({
        listing_id: listingId,
        worker_user_id: candidate.worker_user_id,
        message: contactText,
      });
      setMessage("Message sent to the worker.");
      setShowContact(false);
      setContactText("");
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Could not send the message.");
    } finally {
      setBusy(false);
    }
  }

  async function reportOutcome() {
    setBusy(true);
    setMessage("");
    try {
      await api.kvHireOutcomeReport({
        listing_id: listingId,
        worker_user_id: candidate.worker_user_id,
        outcome,
        note,
      });
      setMessage(`Outcome recorded: ${outcome.replace("_", " ")}.`);
      setShowOutcome(false);
      setNote("");
      onChanged();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : "Could not record the outcome.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
      <div className="flex items-start gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-accent/15 text-accent ring-1 ring-accent/30">
          <User size={22} aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="font-serif text-xl leading-snug">{candidate.worker_name || "Worker"}</h3>
          <p className="mt-1 flex items-center gap-1.5 text-xs text-fg-2">
            <Clock size={13} aria-hidden="true" className="shrink-0 text-fg-3" />
            Consent until {fmtDate(candidate.consent_expires_at)}
          </p>
        </div>
        {candidate.is_sample && <KvSampleChip />}
      </div>
      <div className="mt-4">
        <KvMatchMeter value={candidate.match_percent} label="Match" />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2.5">
        <KvComponentBar label="Skills" value={candidate.components.skill} />
        <KvComponentBar label="Job title" value={candidate.components.title} />
        <KvComponentBar label="City" value={candidate.components.city} />
        <KvComponentBar label="Income" value={candidate.components.income} />
      </div>
      {candidate.reasons.length > 0 && (
        <ul className="mt-3 space-y-1.5 rounded-xl bg-white/[0.04] px-3 py-2.5 text-sm text-fg-2 ring-1 ring-white/5">
          {candidate.reasons.map((r, i) => (
            <li key={i} className="flex items-start gap-2">
              <Check size={15} aria-hidden="true" className="mt-0.5 shrink-0 text-ok" />
              <span>{reasonText(r)}</span>
            </li>
          ))}
        </ul>
      )}
      {candidate.missing_skills.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <BookOpen size={14} aria-hidden="true" className="shrink-0 text-fg-3" />
          <span className="text-xs text-fg-2">To learn:</span>
          {candidate.missing_skills.map((s) => (
            <span
              key={s}
              className="inline-flex items-center rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-fg-2 ring-1 ring-white/10"
            >
              {s}
            </span>
          ))}
        </div>
      )}
      <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-white/10 pt-4 text-sm">
        {p.skills && (
          <div className="col-span-2">
            <dt className="text-xs font-semibold uppercase tracking-wider text-fg-3">Can do</dt>
            <dd className="mt-0.5">{p.skills.join(", ")}</dd>
          </div>
        )}
        {p.education && (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wider text-fg-3">Education</dt>
            <dd className="mt-0.5">{p.education}</dd>
          </div>
        )}
        {(p.city || p.district) && (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wider text-fg-3">Place</dt>
            <dd className="mt-0.5">{[p.city, p.district].filter(Boolean).join(", ")}</dd>
          </div>
        )}
        {p.income_monthly != null && (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wider text-fg-3">Needs</dt>
            <dd className="mt-0.5">₹{p.income_monthly.toLocaleString("en-IN")}/month</dd>
          </div>
        )}
        {p.income_text && (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wider text-fg-3">Income</dt>
            <dd className="mt-0.5">{p.income_text}</dd>
          </div>
        )}
        {p.goal_type && (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wider text-fg-3">Looking for</dt>
            <dd className="mt-0.5">{p.goal_type}</dd>
          </div>
        )}
        {p.interests && (
          <div>
            <dt className="text-xs font-semibold uppercase tracking-wider text-fg-3">Interests</dt>
            <dd className="mt-0.5">{p.interests}</dd>
          </div>
        )}
        {p.contact && (
          <div className="col-span-2">
            <dt className="text-xs font-semibold uppercase tracking-wider text-fg-3">Contact</dt>
            <dd className="mt-0.5 break-words">
              {p.contact.email}
              {p.contact.phone_e164 ? ` · ${p.contact.phone_e164}` : ""}
            </dd>
          </div>
        )}
      </dl>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="text-xs text-fg-3">Shared fields:</span>
        {p.fields_shared.map((f) => (
          <span
            key={f}
            className="inline-flex items-center rounded-full bg-white/[0.06] px-2 py-0.5 text-[11px] text-fg-2 ring-1 ring-white/10"
          >
            {f}
          </span>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {!shortlisted && (
          <button type="button" className={kvBtnPrimary} disabled={busy} onClick={shortlist}>
            Shortlist
          </button>
        )}
        <button type="button" className={kvBtnGhost} onClick={() => setShowContact((v) => !v)}>
          {showContact ? "Close" : "Contact"}
        </button>
        <button type="button" className={kvBtnGhost} onClick={() => setShowOutcome((v) => !v)}>
          {showOutcome ? "Close" : "Report outcome"}
        </button>
      </div>
      {shortlisted && (
        <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-ok/10 px-2.5 py-1 text-xs font-medium text-ok ring-1 ring-ok/30">
          <Check size={13} aria-hidden="true" /> Shortlisted for this job.
        </p>
      )}
      {showContact && (
        <div className="mt-3 rounded-xl bg-white/[0.04] p-4 ring-1 ring-white/5">
          <label className="block text-sm text-fg-2">
            Message to the worker
            <textarea
              className={`${kvInputCls} min-h-[64px] resize-y`}
              value={contactText}
              onChange={(e) => setContactText(e.target.value)}
              placeholder="e.g. Can you come for a trial on Monday?"
            />
          </label>
          <button type="button" className={`${kvBtnPrimary} mt-3`} disabled={busy} onClick={contact}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : null}
            Send message
          </button>
        </div>
      )}
      {showOutcome && (
        <div className="mt-3 rounded-xl bg-white/[0.04] p-4 ring-1 ring-white/5">
          <label className="block text-sm text-fg-2">
            What happened?
            <select
              className={kvInputCls}
              value={outcome}
              onChange={(e) => setOutcome(e.target.value as typeof outcome)}
            >
              {OUTCOMES.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </label>
          <label className="mt-3 block text-sm text-fg-2">
            Note (optional)
            <input className={kvInputCls} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Joined Monday" />
          </label>
          <button type="button" className={`${kvBtnPrimary} mt-3`} disabled={busy} onClick={reportOutcome}>
            {busy ? <Loader2 size={15} className="animate-spin" /> : null}
            Record outcome
          </button>
        </div>
      )}
      {message && <p className="mt-2 text-sm">{message}</p>}
    </li>
  );
}

export function KvCandidatesView({ listings }: { listings: KvListing[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(listings[0]?.id ?? null);
  const [city, setCity] = useState("");
  const [candidates, setCandidates] = useState<KvCandidate[]>([]);
  const [sampleData, setSampleData] = useState(false);
  const [shortlist, setShortlist] = useState<KvShortlistEntry[]>([]);
  const [summary, setSummary] = useState<KvOutcomeSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);

  useEffect(() => {
    if (selectedId == null && listings.length > 0) setSelectedId(listings[0].id);
  }, [listings, selectedId]);

  async function loadSide(listingId: number) {
    try {
      const [s, o] = await Promise.all([
        api.kvShortlistGet(listingId),
        api.kvEmployerOutcomes(listingId),
      ]);
      setShortlist(s.shortlist);
      setSummary(o);
    } catch {
      // Side panels are best-effort; the candidate list is the main flow.
    }
  }

  async function search() {
    if (selectedId == null) return;
    setLoading(true);
    setError("");
    setSearched(true);
    try {
      const res = await api.kvMatchingCandidates({
        listing_id: selectedId,
        // The API takes city as a string ("" = no filter); null 422s.
        city: city.trim(),
      });
      setCandidates(res.candidates);
      setSampleData(res.sample_data);
      await loadSide(selectedId);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not find candidates.");
      setCandidates([]);
    } finally {
      setLoading(false);
    }
  }

  async function removeShortlist(workerUserId: string) {
    if (selectedId == null) return;
    await api.kvShortlistRemove(selectedId, workerUserId);
    await loadSide(selectedId);
  }

  if (listings.length === 0) {
    return (
      <div>
        <KvSectionHeader icon={Users} title="Find workers" tone="violet" />
        <div className="mt-4">
          <KvEmptyState icon={Users}>
            No verified jobs yet — matching opens once a job is verified. Only workers who shared their profile with you
            appear here.
          </KvEmptyState>
        </div>
      </div>
    );
  }

  const shortlistedIds = new Set(shortlist.map((s) => s.worker_user_id));

  return (
    <div>
      <KvSectionHeader icon={Users} title="Find workers" tone="violet" />
      <p className="mt-2 text-sm text-fg-2">
        Only workers who shared their profile with you appear here — and only the fields they chose to share. If a
        worker stops sharing, their details disappear.
      </p>
      <div className="mt-4 flex flex-wrap items-end gap-3 rounded-2xl bg-panel p-4 ring-1 ring-white/5">
        <label className="min-w-[200px] flex-1 text-sm text-fg-2">
          Job
          <select
            className={kvInputCls}
            value={selectedId ?? ""}
            onChange={(e) => {
              setSelectedId(Number(e.target.value));
              setSearched(false);
              setCandidates([]);
            }}
          >
            {listings.map((l) => (
              <option key={l.id} value={l.id}>
                {l.title} — {l.city}
              </option>
            ))}
          </select>
        </label>
        <label className="min-w-[140px] flex-1 text-sm text-fg-2">
          City (optional)
          <input className={kvInputCls} value={city} onChange={(e) => setCity(e.target.value)} placeholder="Madurai" />
        </label>
        <button type="button" className={kvBtnPrimary} disabled={loading || selectedId == null} onClick={search}>
          {loading ? <Loader2 size={15} className="animate-spin" /> : <Search size={15} />}
          Find candidates
        </button>
      </div>

      <div className="mt-6" aria-live="polite">
        {loading ? (
          <div className="flex min-h-[20vh] items-center justify-center" role="status">
            <Loader2 className="animate-spin text-fg-3" />
          </div>
        ) : error ? (
          <KvCallout tone="danger">
            <p className="text-sm">{error}</p>
          </KvCallout>
        ) : !searched ? (
          <p className="text-sm text-fg-2">Choose a job and search to see workers who shared their profile with you.</p>
        ) : candidates.length === 0 ? (
          <KvEmptyState icon={Users}>
            No workers have shared their profile with you for this job yet. Workers share from the job page.
          </KvEmptyState>
        ) : (
          <>
            <p className="flex items-center gap-2 text-sm text-fg-2">
              <Users size={15} aria-hidden="true" className="text-accent" />
              <span>
                {candidates.length} {candidates.length === 1 ? "worker" : "workers"} shared with you
              </span>
            </p>
            {sampleData && (
              <p className="mt-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
                Some of these workers are sample data for the Kaam-Vaani demo — they are not real people.
              </p>
            )}
            <ul className="mt-4 space-y-3">
              {candidates.map((c) => (
                <CandidateCard
                  key={c.worker_user_id}
                  candidate={c}
                  listingId={selectedId as number}
                  shortlisted={shortlistedIds.has(c.worker_user_id)}
                  onChanged={() => selectedId != null && loadSide(selectedId)}
                />
              ))}
            </ul>
          </>
        )}
      </div>

      {searched && shortlist.length > 0 && (
        <div className="mt-8">
          <KvSectionHeader icon={Star} title="Shortlist for this job" count={shortlist.length} tone="gold" />
          <ul className="mt-4 space-y-3">
            {shortlist.map((s) => (
              <li key={s.id} className="rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
                <div className="flex items-start gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gold/15 text-gold ring-1 ring-gold/30">
                    <Star size={22} aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h4 className="font-medium">{s.worker_name || "Worker"}</h4>
                    <p className="mt-1 flex items-center gap-1.5 text-sm text-fg-2">
                      <Clock size={13} aria-hidden="true" className="shrink-0 text-fg-3" />
                      Shortlisted {fmtDate(s.created_at)}
                    </p>
                    {s.profile ? (
                      <p className="mt-1 text-sm text-fg-2">
                        {s.profile.skills?.join(", ") || ""}
                        {s.profile.city ? ` · ${s.profile.city}` : ""}
                      </p>
                    ) : (
                      <p className="mt-1 text-sm text-fg-2">
                        Details hidden — this worker stopped sharing with you.
                      </p>
                    )}
                  </div>
                  <KvStatusBadge status={s.consent_status} />
                </div>
                <button type="button" className={`${kvBtnGhost} mt-4`} onClick={() => removeShortlist(s.worker_user_id)}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {searched && summary && (
        <div className="mt-8">
          <KvSectionHeader icon={TrendingUp} title="Outcomes for this job" tone="gold" />
          <div className="mt-4 flex flex-wrap gap-2">
            <KvStat icon={Check} value={summary.counts.hired} label="hired" tone="ok" />
            <KvStat icon={Clock} value={summary.counts.interviewed} label="interviewed" tone="gold" />
            <KvStat icon={User} value={summary.counts.not_hired} label="not hired" />
          </div>
          <div className="mt-3 space-y-1.5 text-sm text-fg-2">
            <p className="flex items-center gap-2">
              <CalendarCheck size={15} aria-hidden="true" className="shrink-0 text-accent" />
              <span>
                Still employed after 30 days:{" "}
                {summary.retention.day30.rate == null
                  ? "not reported yet"
                  : `${pct(summary.retention.day30.rate)} (${summary.retention.day30.still_employed}/${summary.retention.day30.reported} reported)`}
              </span>
            </p>
            <p className="flex items-center gap-2">
              <CalendarCheck size={15} aria-hidden="true" className="shrink-0 text-accent" />
              <span>
                Still employed after 90 days:{" "}
                {summary.retention.day90.rate == null
                  ? "not reported yet"
                  : `${pct(summary.retention.day90.rate)} (${summary.retention.day90.still_employed}/${summary.retention.day90.reported} reported)`}
              </span>
            </p>
          </div>
          {summary.outcomes.length > 0 && (
            <ul className="mt-4 space-y-2">
              {summary.outcomes.map((o) => (
                <li key={o.id} className="rounded-xl bg-panel px-4 py-3 text-sm ring-1 ring-white/5">
                  <span className="font-medium">{o.worker_name || "Worker"}</span>
                  <span
                    className={cn(
                      "ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1",
                      o.outcome === "hired" && "bg-ok/15 text-ok ring-ok/30",
                      o.outcome === "interviewed" && "bg-gold/15 text-gold ring-gold/30",
                      o.outcome === "not_hired" && "bg-white/5 text-fg-2 ring-white/10",
                    )}
                  >
                    {o.outcome.replace("_", " ")}
                  </span>
                  <span className="text-fg-2">
                    {" "}
                    · {fmtDate(o.created_at)}
                    {o.day30_status ? ` · Day 30: ${o.day30_status.replace("_", " ")}` : ""}
                    {o.day90_status ? ` · Day 90: ${o.day90_status.replace("_", " ")}` : ""}
                    {o.note ? ` · ${o.note}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
