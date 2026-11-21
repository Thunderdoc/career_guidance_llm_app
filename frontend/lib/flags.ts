/**
 * Kaam-Vaani feature flags (Stage 1) — frontend mirror of the backend
 * KV_* env flags (career_guidance/config.py).
 *
 * Each flag is read ONCE from its NEXT_PUBLIC_KV_* variable. Default:
 * ON in dev, OFF in production until staged (an explicitly set variable
 * always wins). NOTE: the variables are read literally below, not via a
 * dynamic key — Next.js only inlines NEXT_PUBLIC_* values it can see
 * statically at build time, so `process.env[name]` would always read
 * undefined in the browser bundle.
 *
 * These values are baked into the static export at build time: changing
 * a flag in production means rebuilding (Vercel env vars) — the backend
 * flags, by contrast, take effect on restart. Keep the two sides in
 * sync: a UI surface must never render when its backend route is off.
 */

export type KvFlag = "voice" | "rag" | "employers" | "consent" | "videoCheck" | "pilot";

function parseFlag(raw: string | undefined): boolean {
  if (raw === undefined || raw.trim() === "") {
    return process.env.NODE_ENV !== "production";
  }
  return ["1", "true", "yes", "on"].includes(raw.trim().toLowerCase());
}

export const kvFlags: Record<KvFlag, boolean> = {
  voice: parseFlag(process.env.NEXT_PUBLIC_KV_VOICE),
  rag: parseFlag(process.env.NEXT_PUBLIC_KV_RAG),
  employers: parseFlag(process.env.NEXT_PUBLIC_KV_EMPLOYERS),
  consent: parseFlag(process.env.NEXT_PUBLIC_KV_CONSENT),
  videoCheck: parseFlag(process.env.NEXT_PUBLIC_KV_VIDEO_CHECK),
  pilot: parseFlag(process.env.NEXT_PUBLIC_KV_PILOT),
};

/** True when the named Kaam-Vaani flag is on. */
export function isKvEnabled(flag: KvFlag): boolean {
  return kvFlags[flag];
}
