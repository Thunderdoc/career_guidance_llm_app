/**
 * Low-bandwidth mode — pure decision logic (Phase 8).
 *
 * Precedence rule (the whole contract, kept deliberately tiny so it can
 * be reasoned about and tested in isolation):
 *
 *   1. an explicit manual preference (the settings toggle) always wins;
 *   2. otherwise the browser's Save-Data signal
 *      (`navigator.connection.saveData === true`) turns the mode ON;
 *   3. otherwise the mode is OFF.
 *
 * The manual preference is persisted in localStorage under
 * {@link LOW_BANDWIDTH_KEY} ("on" / "off"; absent = no manual choice)
 * and, for signed-in users, mirrored into the account prefs
 * (`PUT /api/v1/me/prefs`, key `low_bandwidth`) by the context provider
 * in bandwidth-context.tsx — localStorage stays the source the whole
 * app reads synchronously, the server copy only seeds it on a new
 * device when no local choice exists.
 *
 * NOTE (honest test status): this repo has NO frontend test runner
 * (no jest/vitest in frontend/package.json, verified Phase 8), so this
 * logic is not covered by an automated frontend test suite. It is kept
 * pure and dependency-free precisely so it can be exercised standalone;
 * Phase 8 verified it by compiling this file with tsc and running the
 * precedence assertions in node by hand (documented manual check in
 * docs/TEST_REPORT.md style — see the Phase 8 CHANGELOG entry).
 */

export const LOW_BANDWIDTH_KEY = "cg.low-bandwidth";

/** The one decision every consumer shares. */
export function resolveLowBandwidth(manual: boolean | null, saveData: boolean): boolean {
  if (manual !== null) return manual;
  return saveData;
}

/** localStorage value → manual preference (`null` = no manual choice). */
export function parseManualPreference(raw: string | null): boolean | null {
  if (raw === "on") return true;
  if (raw === "off") return false;
  return null;
}

/** Manual preference → localStorage value (`null` = remove the key). */
export function serializeManualPreference(manual: boolean | null): string | null {
  if (manual === null) return null;
  return manual ? "on" : "off";
}

/** Account-prefs value (`low_bandwidth`) → manual preference. */
export function manualFromPrefs(prefs: Record<string, unknown> | null | undefined): boolean | null {
  const value = prefs?.["low_bandwidth"];
  return typeof value === "boolean" ? value : null;
}

/** Browser Save-Data signal; false everywhere it cannot be read. */
export function detectSaveData(): boolean {
  if (typeof navigator === "undefined") return false;
  const connection = (navigator as { connection?: { saveData?: boolean } }).connection;
  return connection?.saveData === true;
}

/* ------------------------------------------------------------------ */
/* Effective-mode signal for the Motion primitives.
 *
 * components/motion.tsx must NOT import the React context module: that
 * module also pulls in the API/auth chain, and importing it from the
 * shared Motion primitives dragged ~39 kB into light routes (measured:
 * /shared/[token] 217 → 256 kB). This tiny external store lives in the
 * pure module instead; BandwidthProvider writes it, Motion reads it
 * via useSyncExternalStore.
 * ------------------------------------------------------------------ */
let signalValue = false;
const signalSubscribers = new Set<() => void>();

export function setLowBandwidthSignal(value: boolean): void {
  if (signalValue === value) return;
  signalValue = value;
  signalSubscribers.forEach((fn) => fn());
}

export function subscribeLowBandwidth(fn: () => void): () => void {
  signalSubscribers.add(fn);
  return () => signalSubscribers.delete(fn);
}

export function getLowBandwidthSignal(): boolean {
  return signalValue;
}
