"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowLeft, Check, KeyRound, Loader2, Mail, MailCheck, Sparkles, Target, TrendingUp, BookOpen } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { auth } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { UnverifiedEmailError, firebaseConfigured, friendlyFirebaseError, resendVerification, resetPassword, signInWithEmail, signInWithGoogle, signUpWithEmail } from "@/lib/firebase";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";
import { AnimatedGroup, TextEffect, TextLoop } from "./motion";

type Providers = { firebase: boolean; google: boolean; magic_link: boolean; email_delivery: boolean };

const PERKS = [
  { icon: <Target size={16} />, k: "perk_1" },
  { icon: <TrendingUp size={16} />, k: "perk_2" },
  { icon: <BookOpen size={16} />, k: "perk_3" },
] as const;

export function LoginPage() {
  const { t } = useI18n();
  const { user, refresh, loading } = useAuth();
  const [providers, setProviders] = useState<Providers | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [busy, setBusy] = useState<"" | "google" | "email" | "magic" | "reset" | "resend">("");
  const [notice, setNotice] = useState<{ kind: "ok" | "err" | "verify"; text: string; link?: string } | null>(null);
  const [unverified, setUnverified] = useState(false);
  const next = typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("next") || "/" : "/";

  useEffect(() => {
    auth
      .providers()
      .then((p) => setProviders({ ...p, firebase: p.firebase && firebaseConfigured }))
      .catch(() => setProviders({ firebase: false, google: false, magic_link: true, email_delivery: false }));
    const q = new URLSearchParams(window.location.search);
    if (q.get("verified") === "1") setNotice({ kind: "ok", text: t("verified_banner") });
    if (q.get("reason") === "auth") setNotice({ kind: "err", text: t("login_required") });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!loading && user) window.location.replace(next.startsWith("/") ? next : "/");
  }, [user, loading, next]);

  const finish = async (idToken: string) => {
    await auth.firebase(idToken);
    await refresh();
  };
  const run = async (kind: typeof busy, fn: () => Promise<void>) => {
    setBusy(kind);
    setNotice(null);
    try {
      await fn();
    } catch (e) {
      if (e instanceof UnverifiedEmailError) {
        setUnverified(true);
        setNotice({ kind: "verify", text: t("verify_blocked") });
      } else {
        setNotice({ kind: "err", text: friendlyFirebaseError(e) });
      }
    } finally {
      setBusy("");
    }
  };

  const submitEmail = () =>
    run("email", async () => {
      setUnverified(false);
      if (mode === "signup") {
        const r = await signUpWithEmail(email, password);
        setMode("signin");
        setUnverified(true);
        setNotice({ kind: "verify", text: t("verify_sent", { email: r.email }) });
        return;
      }
      await finish(await signInWithEmail(email, password));
    });

  const resend = () =>
    run("resend", async () => {
      await resendVerification(email, password);
      setNotice({ kind: "verify", text: t("verify_resent", { email }) });
    });

  const fb = providers?.firebase;

  return (
    <div className="relative grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      {/* Left: brand panel */}
      <aside className="relative hidden overflow-hidden bg-bg-2 p-12 lg:flex lg:flex-col lg:justify-between">
        <div className="spotlight left-[-20%] top-[-20%] h-[36rem] w-[36rem] bg-accent/35" />
        <div className="spotlight bottom-[-20%] right-[-10%] h-[28rem] w-[28rem] bg-gold/25 [animation-delay:-7s]" />
        <Link href="/" className="relative flex items-center gap-3 text-sm text-fg-2 hover:text-fg">
          <span className="grid h-9 w-9 place-items-center rounded-[var(--radius-md)] bg-accent/15 text-accent ring-1 ring-accent/30">
            <Sparkles size={18} />
          </span>
          {t("app_name")}
        </Link>
        <div className="relative max-w-md">
          <TextEffect as="h1" per="word" className="font-serif text-5xl leading-[1.05] tracking-tight">
            {t("login_hero")}
          </TextEffect>
          <div className="mt-4 text-lg text-fg-2">
            <TextLoop items={[t("loop_1"), t("loop_2"), t("loop_3")]} />
          </div>
          <AnimatedGroup className="mt-10 flex flex-col gap-3" preset="blur-slide">
            {PERKS.map((p) => (
              <div key={p.k} className="flex items-center gap-3 rounded-2xl bg-bg-3/70 px-4 py-3 text-sm text-fg-2 ring-1 ring-white/5 backdrop-blur">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-accent/15 text-accent">{p.icon}</span>
                {t(p.k)}
              </div>
            ))}
          </AnimatedGroup>
        </div>
        <p className="relative text-[11px] text-fg-3">{t("sign_in_privacy")}</p>
      </aside>

      {/* Right: form */}
      <main className="relative flex items-center justify-center px-5 py-10">
        <div className="spotlight right-[-30%] top-[-20%] h-[30rem] w-[30rem] bg-accent/20 lg:hidden" />
        <motion.div
          initial={{ opacity: 0, y: 18, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
          className="relative w-full max-w-[400px]"
        >
          <Link href="/" className="mb-6 inline-flex items-center gap-1 text-xs text-fg-3 hover:text-fg lg:hidden">
            <ArrowLeft size={14} /> {t("back_home")}
          </Link>
          <div className="rounded-[24px] bg-panel p-7 shadow-[var(--shadow-lg)] ring-1 ring-white/10">
            <AnimatePresence mode="wait">
              <motion.h2 key={mode} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} className="font-serif text-3xl">
                {mode === "signup" && fb ? t("create_account") : t("welcome_back")}
              </motion.h2>
            </AnimatePresence>
            <p className="mt-1 text-sm text-fg-2">{t("sign_in_sub")}</p>

            {providers === null || loading ? (
              <div className="mt-8 flex justify-center">
                <Loader2 className="animate-spin text-fg-3" />
              </div>
            ) : fb ? (
              <>
                <button
                  onClick={() => run("google", async () => finish(await signInWithGoogle()))}
                  disabled={!!busy}
                  className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-white px-4 py-3 text-sm font-medium text-black transition hover:bg-white/90 hover:shadow-[0_0_28px_rgba(255,255,255,0.15)] disabled:opacity-60"
                >
                  {busy === "google" ? <Loader2 size={16} className="animate-spin" /> : <GoogleMark />} {t("continue_google")}
                </button>
                <div className="my-5 flex items-center gap-3 text-[11px] uppercase tracking-wider text-fg-3">
                  <span className="h-px flex-1 bg-white/10" /> {t("or")} <span className="h-px flex-1 bg-white/10" />
                </div>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    submitEmail();
                  }}
                  className="flex flex-col gap-3"
                >
                  <Field id="email" type="email" icon={<Mail size={16} />} label={t("email")} value={email} onChange={setEmail} placeholder="you@example.com" autoFocus />
                  <Field id="password" type="password" icon={<KeyRound size={16} />} label={t("password")} value={password} onChange={setPassword} placeholder="••••••••" minLength={6} />
                  <button
                    type="submit"
                    disabled={!!busy || !email || password.length < 6}
                    className="mt-1 flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-black shadow-[0_0_24px_rgba(0,212,170,0.25)] transition hover:brightness-110 disabled:opacity-50 disabled:shadow-none"
                  >
                    {busy === "email" && <Loader2 size={16} className="animate-spin" />}
                    {mode === "signup" ? t("create_account") : t("sign_in")}
                  </button>
                  <div className="flex items-center justify-between text-xs text-fg-3">
                    <button type="button" onClick={() => setMode(mode === "signup" ? "signin" : "signup")} className="hover:text-accent">
                      {mode === "signup" ? t("have_account") : t("no_account")}
                    </button>
                    <button
                      type="button"
                      disabled={busy === "reset"}
                      onClick={() =>
                        run("reset", async () => {
                          if (!email) throw new Error(t("enter_email_first"));
                          await resetPassword(email);
                          setNotice({ kind: "ok", text: t("reset_sent", { email }) });
                        })
                      }
                      className="hover:text-fg"
                    >
                      {t("forgot_password")}
                    </button>
                  </div>
                </form>
              </>
            ) : (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  run("magic", async () => {
                    const r = await auth.magicLink(email, next);
                    setNotice({ kind: "ok", text: t("link_sent_sub", { email }), link: r.dev_link });
                  });
                }}
                className="mt-6 flex flex-col gap-3"
              >
                <Field id="email" type="email" icon={<Mail size={16} />} label={t("email")} value={email} onChange={setEmail} placeholder="you@example.com" autoFocus />
                <button type="submit" disabled={!!busy || !email} className="flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-black disabled:opacity-50">
                  {busy === "magic" ? <Loader2 size={16} className="animate-spin" /> : <Mail size={16} />} {t("send_link")}
                </button>
              </form>
            )}

            <AnimatePresence>
              {notice && (
                <motion.div
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  role="status"
                  className={cn(
                    "mt-4 rounded-xl p-3 text-xs",
                    notice.kind === "ok" && "bg-accent/10 text-fg-2 ring-1 ring-accent/20",
                    notice.kind === "verify" && "bg-gold/10 text-fg ring-1 ring-gold/30",
                    notice.kind === "err" && "bg-danger/10 text-red-300 ring-1 ring-danger/30",
                  )}
                >
                  <div className="flex items-start gap-2">
                    {notice.kind === "ok" && <Check size={14} className="mt-0.5 shrink-0 text-accent" />}
                    {notice.kind === "verify" && <MailCheck size={14} className="mt-0.5 shrink-0 text-gold" />}
                    <span>{notice.text}</span>
                  </div>
                  {unverified && fb && (
                    <button
                      type="button"
                      onClick={resend}
                      disabled={!!busy || !email || password.length < 6}
                      title={password.length < 6 ? t("resend_needs_password") : undefined}
                      className="mt-2 inline-flex items-center gap-1 rounded-lg bg-gold/15 px-3 py-1.5 text-gold ring-1 ring-gold/30 hover:bg-gold/25 disabled:opacity-50"
                    >
                      {busy === "resend" ? <Loader2 size={12} className="animate-spin" /> : <Mail size={12} />} {t("resend_verification")}
                    </button>
                  )}
                  {notice.link && (
                    <a href={notice.link} className="mt-2 block truncate rounded-lg bg-gold/10 px-3 py-2 text-gold ring-1 ring-gold/30">
                      {t("dev_link")} →
                    </a>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <p className="mt-4 text-center text-[11px] text-fg-3 lg:hidden">{t("sign_in_privacy")}</p>
        </motion.div>
      </main>
    </div>
  );
}

function Field({ id, type, icon, label, value, onChange, placeholder, autoFocus, minLength }: { id: string; type: string; icon: React.ReactNode; label: string; value: string; onChange: (v: string) => void; placeholder: string; autoFocus?: boolean; minLength?: number }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs text-fg-3" htmlFor={id}>
        {label}
      </label>
      <div className="flex items-center gap-2 rounded-xl bg-bg-4 px-3 ring-1 ring-white/5 transition focus-within:ring-accent">
        <span className="text-fg-3">{icon}</span>
        <input id={id} type={type} required autoFocus={autoFocus} minLength={minLength} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className="w-full bg-transparent py-3 text-sm text-fg placeholder:text-fg-3 focus:outline-none" />
      </div>
    </div>
  );
}

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.6 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.3l7.8 6C12.3 13.6 17.7 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z" />
      <path fill="#FBBC05" d="M10.4 28.7A14.5 14.5 0 0 1 9.5 24c0-1.6.3-3.2.8-4.7l-7.8-6A24 24 0 0 0 0 24c0 3.9.9 7.5 2.6 10.7l7.8-6z" />
      <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.9 2.3-8.4 2.3-6.3 0-11.7-4.1-13.6-9.9l-7.8 6C6.5 42.6 14.6 48 24 48z" />
    </svg>
  );
}
