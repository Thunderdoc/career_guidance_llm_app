"use client";

/**
 * Lightweight i18n: a typed dictionary for en / ta / hi and a React context.
 * Career content (O*NET titles, skills) stays in English; the chrome, hero,
 * composer, and status copy are translated.
 *
 * Phase 10 bundle split: only the EN dictionary (the bundled base in
 * ``i18n-dict-en.ts``) ships in the initial bundle. The TA and HI
 * dictionaries live in their own chunks (``i18n-dict-ta.ts`` /
 * ``i18n-dict-hi.ts``) and are loaded on demand with ``import()`` the
 * first time that locale is selected — the language switcher keeps the
 * current locale on screen until the chunk has arrived, so there is no
 * flash of the wrong language. The persisted choice (localStorage
 * ``cg.locale``) is honoured on load the same way. Key type safety is
 * unchanged: ``Dict``/``Key`` are derived from the EN dictionary and the
 * TA/HI modules are typed ``Dict``, so a missing key is a TS error.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { en, type Dict, type Key } from "./i18n-dict-en";

export type { Dict, Key };

export type Locale = "en" | "ta" | "hi";

export const LOCALES: { id: Locale; label: string; native: string }[] = [
  { id: "en", label: "English", native: "English" },
  { id: "ta", label: "Tamil", native: "தமிழ்" },
  { id: "hi", label: "Hindi", native: "हिन्दी" },
];

/** On-demand loaders for the non-base dictionaries (separate chunks). */
const LOADERS: Record<Exclude<Locale, "en">, () => Promise<Dict>> = {
  ta: () => import("./i18n-dict-ta").then((m) => m.ta),
  hi: () => import("./i18n-dict-hi").then((m) => m.hi),
};

const STORAGE_KEY = "cg.locale";

function isLocale(value: string | null): value is Locale {
  return value === "en" || value === "ta" || value === "hi";
}

type Ctx = {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: Key, vars?: Record<string, string | number>) => string;
};

const I18nContext = createContext<Ctx>({
  locale: "en",
  setLocale: () => {},
  t: (k) => en[k],
});

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("en");
  const [dicts, setDicts] = useState<Partial<Record<Locale, Dict>>>({ en });
  const dictsRef = useRef(dicts);
  dictsRef.current = dicts;
  const pendingRef = useRef<Partial<Record<Locale, Promise<Dict>>>>({});

  /** Load a locale's dictionary chunk (once), then make it available. */
  const ensureDict = useCallback(async (l: Locale): Promise<Dict> => {
    const have = dictsRef.current[l];
    if (have) return have;
    if (l === "en") return en;
    let pending = pendingRef.current[l];
    if (!pending) {
      pending = LOADERS[l as Exclude<Locale, "en">]();
      pendingRef.current[l] = pending;
    }
    const dict = await pending;
    setDicts((prev) => (prev[l] ? prev : { ...prev, [l]: dict }));
    return dict;
  }, []);

  /** Switch locale, awaiting the dictionary chunk first (no flash). */
  const applyLocale = useCallback(
    async (l: Locale) => {
      await ensureDict(l);
      setLocaleState(l);
    },
    [ensureDict],
  );

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (isLocale(saved)) {
      void applyLocale(saved);
    } else {
      const nav = navigator.language?.slice(0, 2);
      if (nav === "ta" || nav === "hi") void applyLocale(nav);
    }
  }, [applyLocale]);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback(
    (l: Locale) => {
      window.localStorage.setItem(STORAGE_KEY, l);
      void applyLocale(l);
    },
    [applyLocale],
  );

  const t = useCallback(
    (key: Key, vars?: Record<string, string | number>) => {
      let s = dicts[locale]?.[key] ?? en[key] ?? key;
      if (vars) for (const [k, v] of Object.entries(vars)) s = s.replace(`{${k}}`, String(v));
      return s;
    },
    [dicts, locale],
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}
