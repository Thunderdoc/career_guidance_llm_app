"use client";

/**
 * Phase 5 — plain-language privacy notice.
 *
 * The summary sections are translated (EN/TA/HI via i18n keys). The full
 * legal text below them is English-only today, like the other legal
 * pages (/terms, /refund); the translated summary says so honestly
 * (p5_notice_full_en_note) instead of pretending otherwise.
 */

import { useI18n, type Key } from "@/lib/i18n";

const SUMMARY: { h: Key; b: Key }[] = [
  { h: "p5_notice_collect_h", b: "p5_notice_collect_b" },
  { h: "p5_notice_why_h", b: "p5_notice_why_b" },
  { h: "p5_notice_minor_h", b: "p5_notice_minor_b" },
  { h: "p5_notice_rights_h", b: "p5_notice_rights_b" },
  { h: "p5_notice_consent_h", b: "p5_notice_consent_b" },
];

const FULL_EN: { h: string; b: string }[] = [
  {
    h: "AI features",
    b: "Optional AI features, when enabled, may send your skills and interests to an AI provider to generate explanations. They are labelled as AI-generated and are never presented as verified facts. The core matching engine runs locally on our own catalogue.",
  },
  {
    h: "Institutes",
    b: "If your school or institute enrolled you, its staff see group totals for their cohort. Individual details are visible only to your institute's own staff — and, if you are under 18 without guardian consent, you do not appear on their individual attention list at all.",
  },
  {
    h: "How long we keep data",
    b: "Your data stays while your account exists. Deleting your account removes it as described above; anonymised feedback ratings and aggregate statistics that cannot identify you may be kept.",
  },
  {
    h: "Contact",
    b: "Questions about this notice or your data: [Contact email].",
  },
];

export function PrivacyNoticeView() {
  const { t, locale } = useI18n();
  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-12">
      <h1 className="font-serif text-4xl">Privacy Policy</h1>
      <p className="mt-2 text-sm text-fg-2">Last updated: November 2026.</p>
      {locale !== "en" && <p className="mt-2 text-sm text-fg-3">{t("p5_notice_full_en_note")}</p>}
      <div className="mt-8 space-y-6 text-sm leading-relaxed text-fg-2">
        {SUMMARY.map((s) => (
          <section key={s.h}>
            <h2 className="font-serif text-xl text-white">{t(s.h)}</h2>
            <p className="mt-2">{t(s.b)}</p>
          </section>
        ))}
        {FULL_EN.map((s) => (
          <section key={s.h}>
            <h2 className="font-serif text-xl text-white">{s.h}</h2>
            <p className="mt-2">{s.b}</p>
          </section>
        ))}
        <p className="text-xs text-fg-3">
          This service is designed to support India&apos;s Digital Personal Data Protection Act,
          2023 — see <a className="underline" href="/methodology">how the product works</a>. This
          page describes what the software does; it is not legal advice.
        </p>
      </div>
    </main>
  );
}
