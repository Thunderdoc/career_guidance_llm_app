"use client";

import { AnimatePresence, motion } from "motion/react";
import { Check, KeyRound, Loader2, LogIn, Mail, X } from "lucide-react";
import { useEffect, useState } from "react";
import { auth } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { emailPasswordIdToken, friendlyFirebaseError, googleIdToken, resetPassword } from "@/lib/firebase";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/cn";

type Providers = { firebase: boolean; google: boolean; magic_link: boolean; email_delivery: boolean };

export function AuthDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useI18n();
  const { refresh } = useAuth();
  const [providers, setProviders] = useState<Providers | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [busy, setBusy] = useState<"" | "google" | "email" | "magic" | "reset">("");
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string; link?: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    setNotice(null);
    auth.providers().then(setProviders).catch(() => setProviders({ firebase: false, google: false, magic_link: true, email_delivery: false }));
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [open, onClose]);

  const finish = async (idToken: string) => {
    await auth.firebase(idToken);
    await refresh();
    onClose();
  };

  const withGoogle = async () => {
    setBusy("google");
    setNotice(null);
    try {
      await finish(await googleIdToken());
    } catch (e) {
      setNotice({ kind: "err", text: friendlyFirebaseError(e) });
    } finally {
      setBusy("");
    }
  };

  const withEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("email");
    setNotice(null);
    try {
      await finish(await emailPasswordIdToken(email, password, mode));
    } catch (e) {
      setNotice({ kind: "err", text: friendlyFirebaseError(e) });
    } finally {
      setBusy("");
    }
  };

  const withMagic = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy("magic");
    setNotice(null);
    try {
      const r = await auth.magicLink(email, window.location.pathname);
      setNotice({ kind: "ok", text: t("link_sent_sub", { email }), link: r.dev_link });
    } catch (e) {
      setNotice({ kind: "err", text: (e as Error).message });
    } finally {
      setBusy("");
    }
  };

  const forgot = async () => {
    if (!email) return setNotice({ kind: "err", text: t("enter_email_first") });
    setBusy("reset");
    try {
      await resetPassword(email);
      setNotice({ kind: "ok", text: t("reset_sent", { email }) });
    } catch (e) {
      setNotice({ kind: "err", text: friendlyFirebaseError(e) });
    } finally {
      setBusy("");
    }
  };

  const fb = providers?.firebase;

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="fixed inset-0 z-40 bg-black/60 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={onClose} />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
            <motion.div
              role="dialog"
              aria-modal="true"
              aria-label={t("sign_in")}
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
              onClick={(e) => e.stopPropagation()}
              className="relative w-full max-w-sm overflow-hidden rounded-[20px] bg-panel p-6 shadow-[var(--shadow-lg)] ring-1 ring-white/10"
            >
              <div className="spotlight left-[-30%] top-[-40%] h-64 w-64 bg-accent/30" />
              <button onClick={onClose} aria-label="Close" className="absolute right-3 top-3 rounded-full p-1.5 text-fg-3 hover:bg-bg-3 hover:text-fg">
                <X size={16} />
              </button>
              <div className="relative">
                <div className="grid h-10 w-10 place-items-center rounded-xl bg-accent/15 text-accent ring-1 ring-accent/30">
                  <LogIn size={18} />
                </div>
                <h2 className="mt-3 font-serif text-2xl">{mode === "signup" && fb ? t("create_account") : t("sign_in")}</h2>
                <p className="mt-1 text-sm text-fg-2">{t("sign_in_sub")}</p>

                {providers === null ? (
                  <Loader2 className="mt-6 animate-spin text-fg-3" size={18} />
                ) : fb ? (
                  <>
                    <button
                      onClick={withGoogle}
                      disabled={!!busy}
                      className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-medium text-black transition hover:bg-white/90 disabled:opacity-60"
                    >
                      {busy === "google" ? <Loader2 size={16} className="animate-spin" /> : <GoogleMark />} {t("continue_google")}
                    </button>
                    <div className="my-4 flex items-center gap-3 text-[11px] uppercase tracking-wider text-fg-3">
                      <span className="h-px flex-1 bg-white/10" /> {t("or")} <span className="h-px flex-1 bg-white/10" />
                    </div>
                    <form onSubmit={withEmail} className="flex flex-col gap-2">
                      <Input id="auth-email" type="email" icon={<Mail size={16} />} value={email} onChange={setEmail} placeholder="you@example.com" label={t("email")} autoFocus />
                      <Input id="auth-pass" type="password" icon={<KeyRound size={16} />} value={password} onChange={setPassword} placeholder="••••••••" label={t("password")} minLength={6} />
                      <button
                        type="submit"
                        disabled={!!busy || !email || password.length < 6}
                        className="mt-1 flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-medium text-black transition hover:brightness-110 disabled:opacity-50"
                      >
                        {busy === "email" && <Loader2 size={16} className="animate-spin" />}
                        {mode === "signup" ? t("create_account") : t("sign_in")}
                      </button>
                      <div className="flex justify-between text-[11px] text-fg-3">
                        <button type="button" onClick={() => setMode(mode === "signup" ? "signin" : "signup")} className="hover:text-fg">
                          {mode === "signup" ? t("have_account") : t("no_account")}
                        </button>
                        <button type="button" onClick={forgot} disabled={busy === "reset"} className="hover:text-fg">
                          {t("forgot_password")}
                        </button>
                      </div>
                    </form>
                  </>
                ) : (
                  <form onSubmit={withMagic} className="mt-5 flex flex-col gap-2">
                    <Input id="auth-email" type="email" icon={<Mail size={16} />} value={email} onChange={setEmail} placeholder="you@example.com" label={t("email")} autoFocus />
                    <button
                      type="submit"
                      disabled={!!busy || !email}
                      className="mt-1 flex items-center justify-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-medium text-black transition hover:brightness-110 disabled:opacity-50"
                    >
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
                      className={cn("mt-3 rounded-xl p-3 text-xs", notice.kind === "ok" ? "bg-accent/10 text-fg-2 ring-1 ring-accent/20" : "bg-danger/10 text-red-300 ring-1 ring-danger/30")}
                    >
                      <div className="flex items-start gap-2">
                        {notice.kind === "ok" && <Check size={14} className="mt-0.5 shrink-0 text-accent" />}
                        <span>{notice.text}</span>
                      </div>
                      {notice.link && (
                        <a href={notice.link} className="mt-2 block truncate rounded-lg bg-gold/10 px-3 py-2 text-gold ring-1 ring-gold/30">
                          {t("dev_link")} →
                        </a>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
                <p className="mt-4 text-[11px] leading-snug text-fg-3">{t("sign_in_privacy")}</p>
              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
}

function Input({
  id, type, icon, value, onChange, placeholder, label, autoFocus, minLength,
}: { id: string; type: string; icon: React.ReactNode; value: string; onChange: (v: string) => void; placeholder: string; label: string; autoFocus?: boolean; minLength?: number }) {
  return (
    <>
      <label className="text-xs text-fg-3" htmlFor={id}>
        {label}
      </label>
      <div className="flex items-center gap-2 rounded-xl bg-bg-4 px-3 ring-1 ring-white/5 focus-within:ring-accent">
        <span className="text-fg-3">{icon}</span>
        <input
          id={id}
          type={type}
          required
          autoFocus={autoFocus}
          minLength={minLength}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full bg-transparent py-2.5 text-sm text-fg placeholder:text-fg-3 focus:outline-none"
        />
      </div>
    </>
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
