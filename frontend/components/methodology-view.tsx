"use client";

/**
 * Phase 5 — /methodology: how matching works, the Reality Score with its
 * real weights (career_guidance/reality.py + matching2.py), data sources
 * mirroring docs/SOURCES.md, known limits, and the guidance-not-a-
 * guarantee line. Headings/body come from i18n keys (EN/TA/HI); the
 * weights table shows the actual constants.
 */

import { useI18n, type Key } from "@/lib/i18n";
import { SourceLabel } from "./ui";

const REALITY_WEIGHTS: { label: string; weight: string }[] = [
  { label: "Entry demand", weight: "30%" },
  { label: "AI exposure (lower is safer)", weight: "20%" },
  { label: "Salary ladder", weight: "20%" },
  { label: "Barrier to entry (lower barrier scores higher)", weight: "15%" },
  { label: "Time to first job (estimate)", weight: "15%" },
];

const SECTIONS: { h: Key; b: Key }[] = [
  { h: "p5_method_match_h", b: "p5_method_match_b" },
  { h: "p5_method_reality_h", b: "p5_method_reality_b" },
  { h: "p5_method_sources_h", b: "p5_method_sources_b" },
  { h: "p5_method_limits_h", b: "p5_method_limits_b" },
];

export function MethodologyView() {
  const { t } = useI18n();
  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-12">
      <h1 className="font-serif text-4xl">{t("p5_method_title")}</h1>
      <p className="mt-2 text-sm text-fg-2">{t("p5_method_sub")}</p>
      <div className="mt-8 space-y-6 text-sm leading-relaxed text-fg-2">
        {SECTIONS.slice(0, 2).map((s) => (
          <section key={s.h}>
            <h2 className="font-serif text-xl text-white">{t(s.h)}</h2>
            <p className="mt-2">{t(s.b)}</p>
            {s.h === "p5_method_reality_h" && (
              <table className="mt-3 w-full max-w-md text-left text-sm">
                <tbody>
                  {REALITY_WEIGHTS.map((row) => (
                    <tr key={row.label} className="border-b border-white/5">
                      <td className="py-1.5 pr-4">{row.label}</td>
                      <td className="py-1.5 text-right text-white">{row.weight}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        ))}
        {SECTIONS.slice(2).map((s) => (
          <section key={s.h}>
            <h2 className="font-serif text-xl text-white">{t(s.h)}</h2>
            <p className="mt-2">{t(s.b)}</p>
          </section>
        ))}
        <section>
          <h2 className="font-serif text-xl text-white">Matcher weights</h2>
          <p className="mt-2">
            Skills 55% · Interests 30% · Preparation (job zone) 15% — the matcher-v2 weights used
            for every recommendation (career_guidance/matching2.py).
          </p>
        </section>
      </div>
      <SourceLabel text="Sources: docs/SOURCES.md in the project repository (O*NET CC BY 4.0; NCO-2015; labelled India estimates, as of 2026-11-06)" />
    </main>
  );
}
