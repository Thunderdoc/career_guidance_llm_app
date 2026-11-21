"use client";

/**
 * /sharing — worker profile + consent (Kaam-Vaani Stage 6).
 *
 * Plain and functional by design: the design agent owns the polish.
 * The worker saves one shareable work profile, then grants a
 * per-employer, time-limited consent for a specific job. Consent is
 * revocable any time; the audit log shows every grant, revoke,
 * expiry and employer access. English-only in Stage 6 (L37).
 *
 * "Use my voice profile" prefills the form from the confirmed voice
 * session held in sessionStorage (kv.voice.session) — the server
 * never stored it, so the copy lives on this device only.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Building2, Clock, History, Loader2, Mail, Share2, TrendingUp, User, Users, Volume2 } from "lucide-react";
import {
  ApiError,
  api,
  type KvConsent,
  type KvConsentAuditEvent,
  type KvConsentFieldName,
  type KvConsentStatus,
  type KvContactRequest,
  type KvHireOutcome,
  type KvPublicListing,
  type KvVoiceProfile,
  type KvWorkerProfile,
} from "@/lib/api";
import { kvFlags } from "@/lib/flags";
import { speak } from "@/lib/speech";
import { cn } from "@/lib/cn";
import {
  KvCallout,
  KvEmptyState,
  KvFieldOption,
  KvHeader,
  KvSectionHeader,
  KvStatusBadge,
  kvAuditDot,
  kvBtnDanger,
  kvBtnGhost,
  kvBtnPrimary,
  kvInputCls,
  kvLinkAccent,
} from "./kv-portal-ui";
import { RequireAuth } from "./require-auth";

const GOAL_TYPES = ["job", "training", "business", "other"];
const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "hi", label: "Hindi" },
  { value: "ta", label: "Tamil" },
];

function fmtDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString("en-IN");
}

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function SharingDashboard() {
  const [status, setStatus] = useState<KvConsentStatus | null>(null);
  const [profile, setProfile] = useState<KvWorkerProfile | null>(null);
  const [consents, setConsents] = useState<KvConsent[]>([]);
  const [requests, setRequests] = useState<KvContactRequest[]>([]);
  const [audit, setAudit] = useState<KvConsentAuditEvent[]>([]);
  const [outcomes, setOutcomes] = useState<KvHireOutcome[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Profile form state (comma-separated text for skills/interests).
  const [skills, setSkills] = useState("");
  const [education, setEducation] = useState("");
  const [city, setCity] = useState("");
  const [district, setDistrict] = useState("");
  const [incomeMonthly, setIncomeMonthly] = useState("");
  const [incomeText, setIncomeText] = useState("");
  const [goalType, setGoalType] = useState("job");
  const [interests, setInterests] = useState("");
  const [language, setLanguage] = useState("en");
  const [saving, setSaving] = useState(false);

  // Grant panel state (driven by ?listing=ID in the URL).
  const [listingId, setListingId] = useState<number | null>(null);
  const [listing, setListing] = useState<KvPublicListing | null>(null);
  const [grantFields, setGrantFields] = useState<KvConsentFieldName[]>([]);
  const [duration, setDuration] = useState(30);
  const [granting, setGranting] = useState(false);
  const [explanation, setExplanation] = useState("");
  const [listening, setListening] = useState(false);

  const fillForm = useCallback((p: KvWorkerProfile) => {
    setSkills(p.skills.join(", "));
    setEducation(p.education);
    setCity(p.city);
    setDistrict(p.district);
    setIncomeMonthly(p.income_monthly == null ? "" : String(p.income_monthly));
    setIncomeText(p.income_text);
    setGoalType(p.goal_type || "job");
    setInterests(p.interests);
    setLanguage(p.language || "en");
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [statusRes, consentsRes, requestsRes, auditRes, outcomesRes] = await Promise.all([
        api.kvConsentStatus(),
        api.kvConsentMine(),
        api.kvContactRequestsReceived(),
        api.kvConsentAudit(50),
        api.kvMyOutcomes(),
      ]);
      setStatus(statusRes);
      setGrantFields(statusRes.fields.map((f) => f.name));
      setConsents(consentsRes.consents);
      setRequests(requestsRes.requests);
      setAudit(auditRes.events);
      setOutcomes(outcomesRes.outcomes);
      try {
        const mine = await api.kvWorkerProfileGet();
        setProfile(mine.profile);
        fillForm(mine.profile);
      } catch (e) {
        if (!(e instanceof ApiError && e.status === 404)) throw e;
        setProfile(null); // No profile saved yet — the form starts empty.
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load your sharing page.");
    } finally {
      setLoading(false);
    }
  }, [fillForm]);

  useEffect(() => {
    load();
    // ?listing=ID comes from the "Share my profile" button on /jobs.
    const id = new URLSearchParams(window.location.search).get("listing");
    if (id) setListingId(Number(id));
  }, [load]);

  useEffect(() => {
    if (listingId == null) return;
    api
      .kvPublicListing(listingId)
      .then((res) => setListing(res.listing))
      .catch(() => setListing(null));
  }, [listingId]);

  async function saveProfile() {
    setSaving(true);
    setNotice("");
    try {
      const res = await api.kvWorkerProfileSave({
        skills: splitCsv(skills),
        education,
        city,
        district,
        income_monthly: incomeMonthly.trim() === "" ? null : Number(incomeMonthly),
        income_text: incomeText,
        goal_type: goalType,
        interests: interests,
        language,
      });
      setProfile(res.profile);
      fillForm(res.profile);
      setNotice("Work profile saved. Employers still see nothing until you share it with them.");
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "Could not save the profile.");
    } finally {
      setSaving(false);
    }
  }

  function useVoiceProfile() {
    try {
      const raw = sessionStorage.getItem("kv.voice.session");
      if (!raw) {
        setNotice("No voice profile found on this device — try the voice guide first.");
        return;
      }
      const session = JSON.parse(raw) as { profile?: KvVoiceProfile | null; language?: string };
      const p = session.profile;
      if (!p) {
        setNotice("No confirmed voice profile on this device yet — finish the voice guide first.");
        return;
      }
      setSkills(p.skills.join(", "));
      setEducation(p.education);
      setCity(p.city);
      setIncomeMonthly(p.income_monthly == null ? "" : String(p.income_monthly));
      setIncomeText(p.income_text);
      setGoalType(p.goal_type || "job");
      setInterests(p.interests);
      if (session.language) setLanguage(session.language);
      setNotice("Filled from your voice profile — check it and save.");
    } catch {
      setNotice("Could not read the voice profile from this device.");
    }
  }

  async function grant() {
    if (!listing || !profile) return;
    setGranting(true);
    setNotice("");
    setExplanation("");
    try {
      const res = await api.kvConsentGrant({
        employer_id: listing.employer_id,
        listing_id: listing.id,
        fields: grantFields,
        duration_days: duration,
      });
      setExplanation(res.explanation);
      setNotice(`Shared with ${res.employer_name} for ${duration} days. You can take it back any time below.`);
      setConsents((await api.kvConsentMine()).consents);
      setAudit((await api.kvConsentAudit(50)).events);
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "Could not share your profile.");
    } finally {
      setGranting(false);
    }
  }

  async function revoke(id: number) {
    setNotice("");
    try {
      await api.kvConsentRevoke(id);
      setNotice("Sharing stopped — that employer can no longer see your profile.");
      setConsents((await api.kvConsentMine()).consents);
      setAudit((await api.kvConsentAudit(50)).events);
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "Could not stop sharing.");
    }
  }

  async function listen() {
    if (!explanation || listening) return;
    setListening(true);
    const ok = await speak(explanation, "en", { onEnd: () => setListening(false), onError: () => setListening(false) });
    if (!ok) setListening(false);
  }

  if (loading) {
    return (
      <div className="flex min-h-[30vh] items-center justify-center" role="status">
        <Loader2 className="animate-spin text-fg-3" />
      </div>
    );
  }

  if (error) {
    return (
      <KvCallout tone="danger">
        <p className="text-sm">{error}</p>
      </KvCallout>
    );
  }

  const allFields = status?.fields ?? [];

  return (
    <div className="space-y-8">
      {notice && (
        <KvCallout tone="info">
          <p className="text-sm">{notice}</p>
        </KvCallout>
      )}

      <section>
        <KvSectionHeader icon={User} title="Your work profile" />
        <p className="mt-2 text-sm text-fg-2">
          This is what employers can see — only when you share it with them. Nothing here is visible to anyone until
          you grant consent below.
        </p>
        <div className="mt-4 space-y-3 rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
          <label className="block text-sm text-fg-2">
            What you can do (comma-separated)
            <input
              className={kvInputCls}
              value={skills}
              onChange={(e) => setSkills(e.target.value)}
              placeholder="e.g. electrical work, tailoring, driving"
            />
          </label>
          <label className="block text-sm text-fg-2">
            Education
            <input
              className={kvInputCls}
              value={education}
              onChange={(e) => setEducation(e.target.value)}
              placeholder="e.g. 10th pass"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm text-fg-2">
              City
              <input className={kvInputCls} value={city} onChange={(e) => setCity(e.target.value)} placeholder="Madurai" />
            </label>
            <label className="block text-sm text-fg-2">
              District
              <input
                className={kvInputCls}
                value={district}
                onChange={(e) => setDistrict(e.target.value)}
                placeholder="Madurai"
              />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm text-fg-2">
              Income you need (₹/month)
              <input
                className={kvInputCls}
                type="number"
                inputMode="numeric"
                value={incomeMonthly}
                onChange={(e) => setIncomeMonthly(e.target.value)}
                placeholder="12000"
              />
            </label>
            <label className="block text-sm text-fg-2">
              Or in words
              <input
                className={kvInputCls}
                value={incomeText}
                onChange={(e) => setIncomeText(e.target.value)}
                placeholder="e.g. around twelve thousand"
              />
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm text-fg-2">
              What are you looking for?
              <select className={kvInputCls} value={goalType} onChange={(e) => setGoalType(e.target.value)}>
                {GOAL_TYPES.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm text-fg-2">
              Language
              <select className={kvInputCls} value={language} onChange={(e) => setLanguage(e.target.value)}>
                {LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="block text-sm text-fg-2">
            Interests (optional)
            <input
              className={kvInputCls}
              value={interests}
              onChange={(e) => setInterests(e.target.value)}
              placeholder="e.g. farming, machines"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" className={kvBtnPrimary} disabled={saving} onClick={saveProfile}>
              {saving ? <Loader2 size={15} className="animate-spin" /> : null}
              Save work profile
            </button>
            <button type="button" className={kvBtnGhost} onClick={useVoiceProfile}>
              Use my voice profile
            </button>
          </div>
          {profile && (
            <div className="border-t border-white/10 pt-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-fg-3">Saved profile</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {profile.skills.map((s) => (
                  <span
                    key={s}
                    className="inline-flex items-center rounded-full bg-accent/10 px-2.5 py-1 text-xs font-medium text-accent ring-1 ring-accent/30"
                  >
                    {s}
                  </span>
                ))}
                {profile.skills.length === 0 && (
                  <span className="text-sm text-fg-2">No skills listed</span>
                )}
                {profile.education && (
                  <span className="inline-flex items-center rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-fg-2 ring-1 ring-white/10">
                    {profile.education}
                  </span>
                )}
                {profile.city && (
                  <span className="inline-flex items-center rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-fg-2 ring-1 ring-white/10">
                    {profile.city}
                  </span>
                )}
                {profile.income_monthly != null && (
                  <span className="inline-flex items-center rounded-full bg-gold/10 px-2.5 py-1 text-xs font-semibold text-gold ring-1 ring-gold/30">
                    Needs ₹{profile.income_monthly.toLocaleString("en-IN")}/month
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      </section>

      <section>
        <KvSectionHeader icon={Share2} title="Share with an employer" tone="sky" />
        {listingId == null ? (
          <p className="mt-2 text-sm text-fg-2">
            Pick a job on <Link href="/jobs" className="text-accent underline decoration-dotted">/jobs</Link> and choose
            “Share my profile” to share with that employer.
          </p>
        ) : !listing ? (
          <p className="mt-2 text-sm text-fg-2">That job could not be found — it may have been withdrawn.</p>
        ) : !profile ? (
          <p className="mt-2 text-sm text-fg-2">
            Save your work profile above first — there is nothing to share until then.
          </p>
        ) : (
          <div className="mt-4 rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
            <div className="flex items-start gap-3">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-kv-sky/15 text-kv-sky ring-1 ring-kv-sky/30">
                <Building2 size={22} aria-hidden="true" />
              </span>
              <p className="text-sm leading-relaxed">
                Share your profile with <span className="font-medium">{listing.employer_name}</span> for the job{" "}
                <span className="font-medium">{listing.title}</span>?
              </p>
            </div>
            <fieldset className="mt-4">
              <legend className="text-xs font-semibold uppercase tracking-wider text-fg-3">What they can see</legend>
              <div className="mt-2 space-y-2">
                {allFields.map((f) => (
                  <KvFieldOption
                    key={f.name}
                    name={f.name}
                    explanation={f.explanation}
                    checked={grantFields.includes(f.name)}
                    onChange={(checked) =>
                      setGrantFields((prev) => (checked ? [...prev, f.name] : prev.filter((x) => x !== f.name)))
                    }
                  />
                ))}
              </div>
            </fieldset>
            <label className="mt-4 block text-sm text-fg-2">
              For how long?
              <select
                className={kvInputCls}
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
              >
                {(status?.durations_days ?? [7, 30, 90]).map((d) => (
                  <option key={d} value={d}>
                    {d} days
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className={`${kvBtnPrimary} mt-4`}
              disabled={granting || grantFields.length === 0}
              onClick={grant}
            >
              {granting ? <Loader2 size={15} className="animate-spin" /> : null}
              Share my profile
            </button>
            {explanation && (
              <div className="mt-4">
                <KvCallout tone="ok">
                  <p className="text-sm">{explanation}</p>
                </KvCallout>
                <button type="button" className={`${kvBtnGhost} mt-3`} disabled={listening} onClick={listen}>
                  <Volume2 size={15} /> {listening ? "Playing…" : "Listen"}
                </button>
              </div>
            )}
          </div>
        )}
      </section>

      <section>
        <KvSectionHeader icon={Users} title="Who can see your profile" count={consents.length} tone="violet" />
        {consents.length === 0 ? (
          <div className="mt-4">
            <KvEmptyState icon={Users}>Nobody yet — share with an employer above when you are ready.</KvEmptyState>
          </div>
        ) : (
          <ul className="mt-4 space-y-3">
            {consents.map((c) => (
              <li key={c.id} className="rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
                <div className="flex items-start gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-kv-violet/15 text-kv-violet ring-1 ring-kv-violet/30">
                    <Building2 size={22} aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h3 className="font-serif text-xl leading-snug">{c.employer_name}</h3>
                    {c.listing_title && <p className="mt-1 text-sm text-fg-2">For: {c.listing_title}</p>}
                  </div>
                  <KvStatusBadge status={c.status} />
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {c.fields.map((f) => (
                    <span
                      key={f}
                      className="inline-flex items-center rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-fg-2 ring-1 ring-white/10"
                    >
                      {f}
                    </span>
                  ))}
                </div>
                <p className="mt-3 flex items-center gap-1.5 text-sm text-fg-2">
                  <Clock size={14} aria-hidden="true" className="shrink-0 text-fg-3" />
                  Granted {fmtDate(c.granted_at)} · {c.status === "granted" ? `until ${fmtDate(c.expires_at)}` : c.status}
                </p>
                {c.status === "granted" && (
                  <button type="button" className={`${kvBtnDanger} mt-4`} onClick={() => revoke(c.id)}>
                    Stop sharing
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <KvSectionHeader icon={Mail} title="Messages from employers" count={requests.length} tone="coral" />
        {requests.length === 0 ? (
          <div className="mt-4">
            <KvEmptyState icon={Mail}>
              No messages yet. Employers can only message you after you share your profile with them.
            </KvEmptyState>
          </div>
        ) : (
          <ul className="mt-4 space-y-3">
            {requests.map((r) => (
              <li key={r.id} className="rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
                <div className="flex items-start gap-3">
                  <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-kv-coral/15 text-kv-coral ring-1 ring-kv-coral/30">
                    <Mail size={22} aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{r.employer_name}</p>
                    <p className="mt-1 text-sm text-fg-2">
                      About: {r.listing_title} · {fmtDate(r.created_at)}
                    </p>
                  </div>
                </div>
                {r.message && (
                  <p className="mt-3 rounded-xl bg-white/[0.04] px-3 py-2 text-sm ring-1 ring-white/5">{r.message}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <KvSectionHeader icon={TrendingUp} title="Outcomes" count={outcomes.length} tone="gold" />
        {outcomes.length === 0 ? (
          <div className="mt-4">
            <KvEmptyState icon={TrendingUp}>No hire outcomes reported yet.</KvEmptyState>
          </div>
        ) : (
          <ul className="mt-4 space-y-3">
            {outcomes.map((o) => (
              <li key={o.id} className="rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <p className="font-medium">{o.listing_title}</p>
                  <span
                    className={cn(
                      "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1",
                      o.outcome === "hired" && "bg-ok/15 text-ok ring-ok/30",
                      o.outcome === "interviewed" && "bg-gold/15 text-gold ring-gold/30",
                      o.outcome === "not_hired" && "bg-white/5 text-fg-2 ring-white/10",
                    )}
                  >
                    {o.outcome.replace("_", " ")}
                  </span>
                </div>
                <p className="mt-1 text-sm text-fg-2">
                  Reported by {o.reporter_role} · {fmtDate(o.created_at)}
                </p>
                {(o.day30_status || o.day90_status) && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {o.day30_status && (
                      <span className="inline-flex items-center rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-fg-2 ring-1 ring-white/10">
                        Day 30: {o.day30_status.replace("_", " ")}
                      </span>
                    )}
                    {o.day90_status && (
                      <span className="inline-flex items-center rounded-full bg-white/[0.06] px-2.5 py-1 text-xs text-fg-2 ring-1 ring-white/10">
                        Day 90: {o.day90_status.replace("_", " ")}
                      </span>
                    )}
                  </div>
                )}
                {o.note && <p className="mt-2 text-sm">{o.note}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <KvSectionHeader icon={History} title="Your sharing history" tone="sky" />
        <p className="mt-2 text-sm text-fg-2">
          Every time someone gets access to your profile, it is recorded here and cannot be deleted.
        </p>
        {audit.length === 0 ? (
          <div className="mt-4">
            <KvEmptyState icon={History}>Nothing recorded yet.</KvEmptyState>
          </div>
        ) : (
          <ol className="relative mt-4 space-y-2 border-l-2 border-white/10 pl-5">
            {audit.map((e) => (
              <li key={e.id} className="relative rounded-xl bg-panel px-4 py-3 text-sm ring-1 ring-white/5">
                <span
                  aria-hidden="true"
                  className={cn("absolute -left-[27px] top-4 h-3 w-3 rounded-full ring-2 ring-bg", kvAuditDot(e.action))}
                />
                <span className="font-medium">{e.action}</span>
                <span className="text-fg-2">
                  {" "}
                  · employer #{e.employer_id} · {fmtDate(e.created_at)}
                  {e.detail && typeof e.detail === "object" && "fields" in e.detail
                    ? ` · ${(e.detail.fields as string[]).join(", ")}`
                    : ""}
                  {e.detail && typeof e.detail === "object" && "fields_returned" in e.detail
                    ? ` · shared ${(e.detail.fields_returned as string[]).join(", ")}`
                    : ""}
                </span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

export function KvSharingView() {
  if (!kvFlags.consent) {
    return (
      <main className="mx-auto w-full max-w-2xl px-5 pb-20">
        <KvHeader />
        <p className="mt-6 rounded-xl border border-white/15 px-4 py-3 text-sm text-fg-2">
          Profile sharing is not enabled on this deployment.
        </p>
      </main>
    );
  }
  return (
    <RequireAuth>
      <main className="mx-auto w-full max-w-2xl px-5 pb-20">
        <KvHeader>
          <Link href="/jobs" className={kvLinkAccent}>
            See jobs
          </Link>
        </KvHeader>
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-kv-sky/15 text-kv-sky ring-1 ring-kv-sky/30">
            <Share2 size={22} aria-hidden="true" />
          </span>
          <h1 className="font-serif text-3xl">My sharing</h1>
        </div>
        <p className="mt-2 text-sm text-fg-2">
          Your work profile, who can see it, and what happened with it — all in one place. You are in control: share,
          or stop sharing, any time.
        </p>
        <div className="mt-6">
          <SharingDashboard />
        </div>
        <Link href="/" className="mt-8 inline-flex items-center gap-1 text-xs text-fg-3 hover:text-fg">
          <ArrowLeft size={14} /> Back to app
        </Link>
      </main>
    </RequireAuth>
  );
}
