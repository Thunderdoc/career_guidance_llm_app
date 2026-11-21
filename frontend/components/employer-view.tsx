"use client";

/**
 * /employers — Kaam-Vaani employer portal (Stage 5).
 *
 * Signed-in users register a business (status pending until an admin
 * reviews it), then create and manage listings. Every listing runs
 * the scam checker on create/edit and shows its score honestly.
 * Phone verification links a Firebase-verified number (needs phone
 * sign-in enabled in the Firebase console — owner step, L38; the
 * client flow is built but not live-verified, L44).
 *
 * English-only in Stage 5 (L37); the voice flow stays the trilingual
 * surface. Sample data is labelled wherever it appears.
 */
import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowLeft, BadgeCheck, Briefcase, Building2, Clock, Loader2, MapPin, Phone, ShieldAlert, Trash2, Users, Wallet } from "lucide-react";
import { ApiError, api, type KvEmployer, type KvEmployersStatus, type KvListing, type KvListingInput, type KvScamCheck } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { kvFlags } from "@/lib/flags";
import { cn } from "@/lib/cn";
import { kvCategoryForTitle } from "./kv-voice-ui";
import {
  KvCallout,
  KvEmptyState,
  KvHeader,
  KvRiskMeter,
  KvSampleChip,
  KvSectionHeader,
  KvSeverityChip,
  KvStatusBadge,
  kvBtnGhost,
  kvBtnPrimary,
  kvInputCls,
  kvLabelCls,
  kvLinkAccent,
} from "./kv-portal-ui";
import { KvCandidatesView } from "./kv-candidates-view";
import { RequireAuth } from "./require-auth";

function formatPay(listing: KvListing): string {
  if (listing.pay_text) return listing.pay_text;
  const min = listing.pay_monthly_min;
  const max = listing.pay_monthly_max;
  if (min == null && max == null) return "Pay not listed";
  const fmt = (n: number) => `₹${n.toLocaleString("en-IN")}`;
  if (min != null && max != null) return min === max ? `${fmt(min)}/month` : `${fmt(min)}–${fmt(max)}/month`;
  if (min != null) return `${fmt(min)}+/month`;
  return `Up to ${fmt(max as number)}/month`;
}

function CheckResult({ check }: { check: KvScamCheck }) {
  return (
    <div className="mt-4 rounded-2xl bg-panel p-4 ring-1 ring-white/5">
      <h3 className="flex items-center gap-2 text-sm font-medium">
        <ShieldAlert size={15} aria-hidden="true" className="text-gold" /> Scam check
      </h3>
      <div className="mt-3">
        <KvRiskMeter score={check.score} />
      </div>
      {check.flags.length === 0 ? (
        <p className="mt-3 text-sm text-fg-2">No risk signals found. An admin still reviews the listing before it goes live.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {check.flags.map((flag) => (
            <li key={flag.id} className="flex items-start justify-between gap-3 text-sm text-fg-2">
              <span className="flex items-start gap-2">
                <ShieldAlert size={15} className="mt-0.5 shrink-0 text-gold" aria-hidden="true" />
                <span className="text-fg">{flag.message}</span>
              </span>
              <KvSeverityChip severity={flag.severity} />
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-fg-3">
        Checked by {check.driven_by === "llm" ? "the LLM risk score" : "offline rules"}
        {check.llm_status === "not_configured" ? " (no LLM configured — rules only)" : ""}. {check.pay.reason}
      </p>
    </div>
  );
}

const EMPTY_LISTING: KvListingInput = {
  title: "",
  role_category: "",
  description: "",
  city: "",
  district: "",
  state: "Tamil Nadu",
  pay_monthly_min: null,
  pay_monthly_max: null,
  pay_text: "",
  work_type: "full-time",
  shift: "",
  openings: 1,
  requirements: "",
  contact_info: "",
};

function ListingForm({
  initial,
  heading,
  submitLabel,
  onSubmit,
  busy,
}: {
  initial: KvListingInput;
  heading: string;
  submitLabel: string;
  onSubmit: (body: KvListingInput) => Promise<void>;
  busy: boolean;
}) {
  const [form, setForm] = useState<KvListingInput>(initial);
  const [check, setCheck] = useState<KvScamCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const set = (key: keyof KvListingInput, value: string | number | null) =>
    setForm((f) => ({ ...f, [key]: value }));
  const toNumber = (value: string): number | null => {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const n = Number(trimmed);
    return Number.isFinite(n) ? Math.trunc(n) : null;
  };

  async function handleCheck() {
    setError("");
    setChecking(true);
    try {
      const res = await api.kvListingCheck(form);
      setCheck(res.check);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The check failed — please try again.");
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
      <div className="flex items-center gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent/15 text-accent ring-1 ring-accent/30">
          <Briefcase size={18} aria-hidden="true" />
        </span>
        <h3 className="font-serif text-xl">{heading}</h3>
      </div>
      <div className="mt-5 space-y-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-fg-3">The job</p>
        <label className={kvLabelCls}>
          Job title *
          <input className={kvInputCls} value={form.title} onChange={(e) => set("title", e.target.value)} placeholder="e.g. Electrician helper" />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className={kvLabelCls}>
            Role category
            <input className={kvInputCls} value={form.role_category} onChange={(e) => set("role_category", e.target.value)} placeholder="electrician" />
          </label>
          <label className={kvLabelCls}>
            Work type
            <select className={kvInputCls} value={form.work_type} onChange={(e) => set("work_type", e.target.value)}>
              <option value="full-time">Full-time</option>
              <option value="part-time">Part-time</option>
              <option value="contract">Contract</option>
            </select>
          </label>
        </div>
        <label className={kvLabelCls}>
          What is the work? *
          <textarea className={`${kvInputCls} min-h-[96px] resize-y`} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="Describe the work, hours and workplace plainly." />
        </label>
        <p className="pt-1 text-xs font-semibold uppercase tracking-wider text-fg-3">Where</p>
        <div className="grid grid-cols-2 gap-3">
          <label className={kvLabelCls}>
            City *
            <input className={kvInputCls} value={form.city} onChange={(e) => set("city", e.target.value)} placeholder="Madurai" />
          </label>
          <label className={kvLabelCls}>
            District
            <input className={kvInputCls} value={form.district} onChange={(e) => set("district", e.target.value)} placeholder="Madurai" />
          </label>
        </div>
        <p className="pt-1 text-xs font-semibold uppercase tracking-wider text-fg-3">Pay</p>
        <div className="grid grid-cols-2 gap-3">
          <label className={kvLabelCls}>
            Pay per month (min ₹)
            <input className={kvInputCls} inputMode="numeric" value={form.pay_monthly_min ?? ""} onChange={(e) => set("pay_monthly_min", toNumber(e.target.value))} placeholder="12000" />
          </label>
          <label className={kvLabelCls}>
            Pay per month (max ₹)
            <input className={kvInputCls} inputMode="numeric" value={form.pay_monthly_max ?? ""} onChange={(e) => set("pay_monthly_max", toNumber(e.target.value))} placeholder="15000" />
          </label>
        </div>
        <label className={kvLabelCls}>
          Pay note (optional, shown instead of the range)
          <input className={kvInputCls} value={form.pay_text} onChange={(e) => set("pay_text", e.target.value)} placeholder="e.g. ₹500/day + food" />
        </label>
        <p className="pt-1 text-xs font-semibold uppercase tracking-wider text-fg-3">Details</p>
        <div className="grid grid-cols-2 gap-3">
          <label className={kvLabelCls}>
            Shift
            <input className={kvInputCls} value={form.shift} onChange={(e) => set("shift", e.target.value)} placeholder="Day (9am-6pm)" />
          </label>
          <label className={kvLabelCls}>
            Openings
            <input className={kvInputCls} inputMode="numeric" value={form.openings ?? 1} onChange={(e) => set("openings", toNumber(e.target.value) ?? 1)} />
          </label>
        </div>
        <label className={kvLabelCls}>
          What do you need from the worker?
          <textarea className={`${kvInputCls} min-h-[72px] resize-y`} value={form.requirements} onChange={(e) => set("requirements", e.target.value)} placeholder="e.g. 10th pass, basic wiring knowledge." />
        </label>
        <label className={kvLabelCls}>
          How should workers contact you?
          <input className={kvInputCls} value={form.contact_info} onChange={(e) => set("contact_info", e.target.value)} placeholder="Name, phone, address" />
        </label>
        {error && <p className="text-sm text-danger">{error}</p>}
        {check && <CheckResult check={check} />}
        <div className="flex flex-wrap gap-3">
          <button type="button" className={kvBtnPrimary} disabled={busy || !form.title.trim() || !form.description?.trim() || !form.city?.trim()} onClick={() => onSubmit(form)}>
            {busy ? <Loader2 size={16} className="animate-spin" /> : null}
            {submitLabel}
          </button>
          <button type="button" className={kvBtnGhost} disabled={checking || !form.title.trim()} onClick={handleCheck}>
            {checking ? <Loader2 size={16} className="animate-spin" /> : <ShieldAlert size={16} />}
            Check for scam signals first
          </button>
        </div>
        <p className="text-xs text-fg-3">
          Listings go to an admin for review before workers can see them. Never ask workers to pay a fee or share
          Aadhaar, bank details or OTPs — such listings are flagged automatically.
        </p>
      </div>
    </div>
  );
}

function PhoneVerification({ employer, status, onVerified }: { employer: KvEmployer; status: KvEmployersStatus | null; onVerified: () => void }) {
  const { user } = useAuth();
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"idle" | "code" | "done">("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState<import("firebase/auth").ConfirmationResult | null>(null);

  if (employer.phone_verified) {
    return (
      <p className="mt-2 inline-flex items-center gap-2 rounded-full bg-ok/10 px-2.5 py-1 text-sm font-medium text-ok ring-1 ring-ok/30">
        <BadgeCheck size={16} /> Phone verified: {employer.phone_e164}
      </p>
    );
  }
  if (!status?.phone_otp.firebase_configured) {
    return (
      <p className="mt-2 rounded-xl bg-white/[0.04] px-3 py-2 text-sm text-fg-2 ring-1 ring-white/5">
        Phone verification is not available yet — it needs phone sign-in enabled in the Firebase console. Until then,
        verification is by e-mail and admin review.
      </p>
    );
  }

  async function sendCode() {
    setError("");
    setBusy(true);
    try {
      const fb = await import("@/lib/firebase");
      const result = await fb.startPhoneLink(phone.trim());
      setConfirmation(result);
      setStep("code");
    } catch (e) {
      const fb = await import("@/lib/firebase");
      setError(fb.friendlyFirebaseError(e));
    } finally {
      setBusy(false);
    }
  }

  async function confirmCode() {
    if (!confirmation) return;
    setError("");
    setBusy(true);
    try {
      const fb = await import("@/lib/firebase");
      const idToken = await fb.confirmPhoneLink(confirmation, code.trim());
      await api.kvEmployerVerifyPhone(idToken);
      setStep("done");
      onVerified();
    } catch (e) {
      const fb = await import("@/lib/firebase");
      setError(e instanceof ApiError ? e.message : fb.friendlyFirebaseError(e));
    } finally {
      setBusy(false);
    }
  }

  if (step === "done") {
    return <p className="mt-2 text-sm text-ok">Phone verified — thank you.</p>;
  }
  return (
    <div className="mt-3 space-y-3">
      <div id="kv-phone-recaptcha" />
      {step === "idle" ? (
        <>
          <p className="text-sm text-fg-2">
            Verify your phone with an SMS code. First sign in with Google using the same e-mail ({user?.email}) so
            the number links to this account.
          </p>
          <div className="flex flex-wrap gap-3">
            <input className={`${kvInputCls} mt-0 max-w-[240px] flex-1`} value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+919876543210" />
            <button type="button" className={kvBtnGhost} disabled={busy || !phone.trim()} onClick={sendCode}>
              {busy ? <Loader2 size={16} className="animate-spin" /> : <Phone size={16} />}
              Send code
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm text-fg-2">We sent a 6-digit code to {phone}. Enter it below.</p>
          <div className="flex flex-wrap gap-3">
            <input className={`${kvInputCls} mt-0 max-w-[160px] flex-1`} value={code} onChange={(e) => setCode(e.target.value)} placeholder="123456" inputMode="numeric" />
            <button type="button" className={kvBtnPrimary} disabled={busy || code.trim().length < 6} onClick={confirmCode}>
              {busy ? <Loader2 size={16} className="animate-spin" /> : null}
              Verify code
            </button>
          </div>
        </>
      )}
      {error && <p className="text-sm text-danger">{error}</p>}
    </div>
  );
}

function RegisterForm({ onRegistered }: { onRegistered: () => void }) {
  const [form, setForm] = useState({ business_name: "", contact_name: "", phone_e164: "", city: "", district: "", business_type: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const set = (key: keyof typeof form, value: string) => setForm((f) => ({ ...f, [key]: value }));

  async function submit() {
    setError("");
    setBusy(true);
    try {
      await api.kvEmployerRegister(form);
      onRegistered();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Registration failed — please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
      <div className="flex items-center gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gold/15 text-gold ring-1 ring-gold/30">
          <Building2 size={22} aria-hidden="true" />
        </span>
        <h2 className="font-serif text-2xl">Register your business</h2>
      </div>
      <p className="mt-2 text-sm text-fg-2">
        Tell workers who you are. An admin reviews every business before its jobs go live — that review is what keeps
        fake employers out.
      </p>
      <div className="mt-5 space-y-4">
        <label className={kvLabelCls}>
          Business name *
          <input className={kvInputCls} value={form.business_name} onChange={(e) => set("business_name", e.target.value)} placeholder="e.g. Murugan Electricals" />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className={kvLabelCls}>
            Contact person
            <input className={kvInputCls} value={form.contact_name} onChange={(e) => set("contact_name", e.target.value)} placeholder="Your name" />
          </label>
          <label className={kvLabelCls}>
            Phone
            <input className={kvInputCls} value={form.phone_e164} onChange={(e) => set("phone_e164", e.target.value)} placeholder="+919876543210" />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className={kvLabelCls}>
            City
            <input className={kvInputCls} value={form.city} onChange={(e) => set("city", e.target.value)} placeholder="Madurai" />
          </label>
          <label className={kvLabelCls}>
            District
            <input className={kvInputCls} value={form.district} onChange={(e) => set("district", e.target.value)} placeholder="Madurai" />
          </label>
        </div>
        <label className={kvLabelCls}>
          What does your business do?
          <input className={kvInputCls} value={form.business_type} onChange={(e) => set("business_type", e.target.value)} placeholder="e.g. Electrical shop" />
        </label>
        <label className={kvLabelCls}>
          A few lines about the business
          <textarea className={`${kvInputCls} min-h-[80px] resize-y`} value={form.description} onChange={(e) => set("description", e.target.value)} placeholder="What work do you do, how long have you run the business?" />
        </label>
        {error && <p className="text-sm text-danger">{error}</p>}
        <button type="button" className={kvBtnPrimary} disabled={busy || form.business_name.trim().length < 2} onClick={submit}>
          {busy ? <Loader2 size={16} className="animate-spin" /> : null}
          Register business
        </button>
      </div>
    </div>
  );
}

function EmployerDashboard() {
  const { refresh } = useAuth();
  const [employer, setEmployer] = useState<KvEmployer | null>(null);
  const [status, setStatus] = useState<KvEmployersStatus | null>(null);
  const [listings, setListings] = useState<KvListing[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<KvListing | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [lastCheck, setLastCheck] = useState<KvScamCheck | null>(null);

  async function load() {
    setLoading(true);
    setLoadError("");
    try {
      const [statusRes, mineRes, listingsRes] = await Promise.all([
        api.kvEmployersStatus(),
        api.kvEmployerMine(),
        api.kvMyListings(),
      ]);
      setStatus(statusRes);
      setEmployer(mineRes.employer);
      setListings(listingsRes.listings);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        // No employer profile yet — the register form handles it.
        setEmployer(null);
        try {
          setStatus(await api.kvEmployersStatus());
        } catch {
          setStatus(null);
        }
      } else {
        setLoadError(e instanceof ApiError ? e.message : "Could not load the employer portal.");
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleRegistered() {
    await refresh();
    await load();
  }

  async function handleCreate(body: KvListingInput) {
    setBusy(true);
    setNotice("");
    try {
      const res = await api.kvListingCreate(body);
      setLastCheck(res.check);
      setListings((items) => [res.listing, ...items]);
      setShowCreate(false);
      setNotice(
        res.listing.status === "flagged"
          ? "This listing was flagged by the scam check and sent for admin review."
          : "Listing submitted — an admin reviews it before workers can see it.",
      );
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "Could not create the listing.");
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdate(body: KvListingInput) {
    if (!editing) return;
    setBusy(true);
    setNotice("");
    try {
      const res = await api.kvListingUpdate(editing.id, body);
      setLastCheck(res.check);
      setListings((items) => items.map((item) => (item.id === editing.id ? res.listing : item)));
      setEditing(null);
      setNotice("Listing updated — it goes back to admin review before workers see it again.");
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "Could not update the listing.");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(listing: KvListing) {
    if (!window.confirm(`Withdraw "${listing.title}"? Workers will no longer see it.`)) return;
    try {
      await api.kvListingDelete(listing.id);
      setListings((items) => items.filter((item) => item.id !== listing.id));
    } catch (e) {
      setNotice(e instanceof ApiError ? e.message : "Could not delete the listing.");
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center" role="status" aria-live="polite">
        <Loader2 className="animate-spin text-fg-3" />
      </div>
    );
  }
  if (loadError) {
    return (
      <KvCallout tone="danger">
        <p className="text-sm">{loadError}</p>
      </KvCallout>
    );
  }
  if (!employer) {
    return <RegisterForm onRegistered={handleRegistered} />;
  }

  return (
    <div className="space-y-6">
      <section className="rounded-[var(--radius-lg)] bg-panel p-5 ring-1 ring-white/5">
        <div className="flex items-start gap-3">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gold/15 text-gold ring-1 ring-gold/30">
            <Building2 size={22} aria-hidden="true" />
          </span>
          <div className="min-w-0 flex-1">
            <h2 className="font-serif text-2xl leading-snug">{employer.business_name}</h2>
            <p className="mt-1 text-sm text-fg-2">
              {[employer.business_type, employer.city].filter(Boolean).join(" · ")}
              {employer.district && employer.district !== employer.city ? `, ${employer.district}` : ""}
            </p>
          </div>
          <KvStatusBadge status={employer.status} />
        </div>
        {employer.endorsed && (
          <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-ok/10 px-2.5 py-1 text-xs font-medium text-ok ring-1 ring-ok/30">
            <BadgeCheck size={13} aria-hidden="true" /> Endorsed by {employer.endorsed_by}
            {employer.endorsed_by_type ? ` (${employer.endorsed_by_type})` : ""}
          </p>
        )}
        {employer.description && <p className="mt-3 text-sm text-fg-2">{employer.description}</p>}
        {employer.status === "pending" && (
          <div className="mt-4">
            <KvCallout tone="warn">
              <p className="text-sm">
                Your business is waiting for admin review. You can already create listings — they go live only after your
                business and the listing are both verified.
              </p>
            </KvCallout>
          </div>
        )}
        {employer.status === "rejected" && employer.review_note && (
          <div className="mt-4">
            <KvCallout tone="danger">
              <p className="text-sm">Reviewer note: {employer.review_note}</p>
            </KvCallout>
          </div>
        )}
        {employer.status === "flagged" && (
          <div className="mt-4">
            <KvCallout tone="danger">
              <p className="text-sm">
                Your business is flagged for review. {employer.review_note}
              </p>
            </KvCallout>
          </div>
        )}
        <div className="mt-4 border-t border-white/10 pt-4">
          <h3 className="flex items-center gap-2 text-sm font-medium">
            <Phone size={15} /> Phone verification
          </h3>
          <PhoneVerification employer={employer} status={status} onVerified={load} />
        </div>
      </section>

      {notice && (
        <KvCallout tone="info">
          <p className="text-sm">{notice}</p>
        </KvCallout>
      )}
      {lastCheck && <CheckResult check={lastCheck} />}

      <section>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <KvSectionHeader icon={Briefcase} title="Your jobs" count={listings.length} tone="gold" />
          <button type="button" className={kvBtnPrimary} onClick={() => setShowCreate((v) => !v)} disabled={employer.status === "rejected"}>
            {showCreate ? "Close form" : "Post a job"}
          </button>
        </div>
        {employer.status === "rejected" && (
          <p className="mt-2 text-sm text-fg-2">Posting is paused while your business is rejected — fix the issue noted above and ask for a re-review.</p>
        )}
        {showCreate && (
          <div className="mt-4">
            <ListingForm initial={EMPTY_LISTING} heading="Post a job" submitLabel="Submit for review" onSubmit={handleCreate} busy={busy} />
          </div>
        )}
        {editing && (
          <div className="mt-4">
            <ListingForm
              initial={{
                title: editing.title,
                role_category: editing.role_category,
                description: editing.description,
                city: editing.city,
                district: editing.district,
                state: editing.state,
                pay_monthly_min: editing.pay_monthly_min,
                pay_monthly_max: editing.pay_monthly_max,
                pay_text: editing.pay_text,
                work_type: editing.work_type,
                shift: editing.shift,
                openings: editing.openings,
                requirements: editing.requirements,
                contact_info: editing.contact_info,
              }}
              heading={`Edit: ${editing.title}`}
              submitLabel="Save changes"
              onSubmit={handleUpdate}
              busy={busy}
            />
            <button type="button" className={`${kvBtnGhost} mt-3`} onClick={() => setEditing(null)}>
              Cancel editing
            </button>
          </div>
        )}
        {listings.length === 0 ? (
          <div className="mt-4">
            <KvEmptyState icon={Briefcase}>No jobs posted yet. Post your first job above.</KvEmptyState>
          </div>
        ) : (
          <ul className="mt-4 space-y-3">
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
                      <h3 className="font-serif text-xl leading-snug">{listing.title}</h3>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1.5">
                      <KvStatusBadge status={listing.status} />
                      {listing.is_sample && <KvSampleChip />}
                    </div>
                  </div>
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
                  {listing.risk_score > 0 && (
                    <div className="mt-3 rounded-xl border border-white/10 p-3">
                      <KvRiskMeter score={listing.risk_score} />
                      {listing.risk_flags.length > 0 && (
                        <ul className="mt-2 space-y-1.5">
                          {listing.risk_flags.map((f) => (
                            <li key={f.id} className="flex items-start justify-between gap-3 text-sm text-fg-2">
                              <span>{f.message}</span>
                              <KvSeverityChip severity={f.severity} />
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                  {listing.review_note && (
                    <p className="mt-3 rounded-xl bg-white/[0.04] px-3 py-2 text-sm text-fg-2 ring-1 ring-white/5">
                      Reviewer note: {listing.review_note}
                    </p>
                  )}
                  <div className="mt-4 flex flex-wrap gap-2">
                    <button type="button" className={kvBtnGhost} onClick={() => setEditing(listing)}>
                      Edit
                    </button>
                    <button type="button" className={kvBtnGhost} onClick={() => handleDelete(listing)}>
                      <Trash2 size={15} /> Withdraw
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {employer.status === "verified" && kvFlags.consent && (
        <section className="mt-10 border-t border-white/10 pt-8">
          <KvCandidatesView listings={listings.filter((l) => l.status === "verified")} />
        </section>
      )}
    </div>
  );
}

export function EmployerView() {
  if (!kvFlags.employers) {
    return (
      <main className="mx-auto w-full max-w-2xl px-5 pb-20">
        <KvHeader />
        <p className="mt-6 rounded-xl border border-white/15 px-4 py-3 text-sm text-fg-2">
          The employer portal is not enabled on this deployment.
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
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gold/15 text-gold ring-1 ring-gold/30">
            <Building2 size={22} aria-hidden="true" />
          </span>
          <h1 className="font-serif text-3xl">For employers</h1>
        </div>
        <p className="mt-2 text-sm text-fg-2">
          Post jobs for rural workers. Every business and every job is reviewed before workers see it.
        </p>
        <div className="mt-6">
          <EmployerDashboard />
        </div>
        <Link href="/" className="mt-8 inline-flex items-center gap-1 text-xs text-fg-3 hover:text-fg">
          <ArrowLeft size={14} /> Back to app
        </Link>
      </main>
    </RequireAuth>
  );
}
