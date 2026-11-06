"use client";

/**
 * Low-bandwidth context (Phase 8): owns the mode for the whole app.
 *
 * Effects when the mode is ON (all keyed off this one state):
 * - `<html data-low-bandwidth="true">` — globals.css kills CSS
 *   animations/transitions and hides decorative layers (.spotlight,
 *   [data-decorative]) under that attribute;
 * - the shared Motion primitives (components/motion.tsx) read the
 *   effective-mode signal in lib/bandwidth.ts (kept import-light on
 *   purpose) and render statically, extending the existing
 *   prefers-reduced-motion gate to JS-driven animation;
 * - heavy dynamic panels (report chat + share, …) are not mounted by
 *   their parents until the user asks — parents consult this context.
 *
 * State rules: manual toggle (localStorage, see lib/bandwidth.ts) wins;
 * Save-Data auto-enables when no manual choice exists; a signed-in
 * user's saved account pref seeds the manual choice on a device with no
 * local one, and changing the toggle mirrors back to /me/prefs.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { auth as authApi } from "./api";
import { useAuth } from "./auth-context";
import {
  LOW_BANDWIDTH_KEY,
  detectSaveData,
  manualFromPrefs,
  parseManualPreference,
  resolveLowBandwidth,
  serializeManualPreference,
  setLowBandwidthSignal,
} from "./bandwidth";

type BandwidthCtx = {
  lowBandwidth: boolean;
  manual: boolean | null;
  saveData: boolean;
  setManual: (value: boolean | null) => void;
};

const DEFAULT_CTX: BandwidthCtx = {
  lowBandwidth: false,
  manual: null,
  saveData: false,
  setManual: () => {},
};

const BandwidthContext = createContext<BandwidthCtx>(DEFAULT_CTX);

export function BandwidthProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const [manual, setManualState] = useState<boolean | null>(null);
  const [saveData, setSaveData] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const seededForUser = useRef<string | null>(null);

  // Hydrate from localStorage + the Save-Data signal (client only).
  useEffect(() => {
    setManualState(parseManualPreference(window.localStorage.getItem(LOW_BANDWIDTH_KEY)));
    setSaveData(detectSaveData());
    setHydrated(true);
    const connection = (navigator as { connection?: EventTarget }).connection;
    const onChange = () => setSaveData(detectSaveData());
    connection?.addEventListener?.("change", onChange);
    return () => connection?.removeEventListener?.("change", onChange);
  }, []);

  // Seed the manual choice from the account prefs on a device that has
  // no local choice yet (once per signed-in user).
  useEffect(() => {
    if (!hydrated || !user || seededForUser.current === user.id) return;
    seededForUser.current = user.id;
    setManualState((current) => {
      if (current !== null) return current;
      const fromPrefs = manualFromPrefs(user.prefs as Record<string, unknown> | undefined);
      if (fromPrefs !== null) {
        const raw = serializeManualPreference(fromPrefs);
        try {
          if (raw) window.localStorage.setItem(LOW_BANDWIDTH_KEY, raw);
        } catch { /* private mode */ }
      }
      return fromPrefs;
    });
  }, [hydrated, user]);

  const lowBandwidth = resolveLowBandwidth(manual, saveData);

  useEffect(() => {
    // The Motion primitives read the signal (see lib/bandwidth.ts for
    // why they do not import this module); it updates even before
    // hydration completes so a stored choice applies on first paint
    // of animated content.
    setLowBandwidthSignal(lowBandwidth);
    if (!hydrated) return;
    document.documentElement.dataset.lowBandwidth = lowBandwidth ? "true" : "false";
  }, [hydrated, lowBandwidth]);

  const setManual = useCallback(
    (value: boolean | null) => {
      setManualState(value);
      try {
        const raw = serializeManualPreference(value);
        if (raw) window.localStorage.setItem(LOW_BANDWIDTH_KEY, raw);
        else window.localStorage.removeItem(LOW_BANDWIDTH_KEY);
      } catch { /* private mode — the in-memory choice still applies */ }
      if (user) {
        const prefs = { ...((user.prefs as Record<string, unknown>) ?? {}), low_bandwidth: value };
        authApi.setPrefs(prefs).catch(() => { /* local choice already saved */ });
      }
    },
    [user],
  );

  const value = useMemo(
    () => ({ lowBandwidth, manual, saveData, setManual }),
    [lowBandwidth, manual, saveData, setManual],
  );
  return <BandwidthContext.Provider value={value}>{children}</BandwidthContext.Provider>;
}

export function useBandwidth(): BandwidthCtx {
  return useContext(BandwidthContext);
}
