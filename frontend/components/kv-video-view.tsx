"use client";

/**
 * /video-check — video skill check (Kaam-Vaani Step 9.3, EXPERIMENTAL).
 *
 * Plain and functional by design: the design agent owns the polish.
 * This page checks only that a 30–60 s clip is a real recording with
 * visible, moving content. It does NOT assess skill, and the result
 * always says so: "Indicative only — not a certificate." The clip is
 * deleted right after analysis — it is never stored.
 */
import Link from "next/link";
import { useState } from "react";
import { ArrowLeft, Check, Loader2, Upload, Video, X } from "lucide-react";
import { ApiError, api, type KvVideoCheckResult } from "@/lib/api";
import { kvFlags } from "@/lib/flags";
import {
  KvCallout,
  KvEmptyState,
  KvHeader,
  KvSectionHeader,
  kvBtnGhost,
  kvBtnPrimary,
  kvInputCls,
} from "./kv-portal-ui";

export function KvVideoView() {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<KvVideoCheckResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.kvVideoCheck(file);
      setResult(res);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Too many video checks — try again later (5 per hour).");
      } else {
        setError(err instanceof Error ? err.message : "The check failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  if (!kvFlags.videoCheck) {
    return (
      <KvEmptyState icon={Video}>The video skill check is not enabled.</KvEmptyState>
    );
  }

  return (
    <div className="space-y-8">
      <KvHeader>
        <Link href="/" className={kvBtnGhost}>
          <ArrowLeft size={15} aria-hidden="true" /> Home
        </Link>
        <h1 className="font-serif text-3xl">Video skill check</h1>
        <p className="text-sm text-fg-2">
          Experimental. Upload a 30–60 second clip of the task. The check only verifies the
          clip is a real recording with visible, moving content — it does not assess skill.
        </p>
      </KvHeader>

      <KvCallout tone="warn">
        <p>
          <strong>Indicative only — not a certificate.</strong> A usable clip means the
          recording is watchable, not that the skill is proven. A coordinator-led practical
          check is the reliable assessment. Your clip is deleted right after analysis.
        </p>
      </KvCallout>

      <section className="space-y-3" aria-label="Upload a clip">
        <KvSectionHeader icon={Upload} title="Upload a clip" />
        <input
          type="file"
          accept="video/*"
          className={kvInputCls}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          aria-label="Video clip, 30 to 60 seconds, up to 50 MB"
        />
        <p className="text-xs text-fg-2">30–60 seconds, up to 50 MB. 5 checks per hour.</p>
        <div>
          <button type="button" className={kvBtnPrimary} onClick={() => void submit()} disabled={busy || !file}>
            {busy ? <Loader2 size={15} className="animate-spin" aria-hidden="true" /> : <Video size={15} aria-hidden="true" />}
            Check this clip
          </button>
        </div>
        {error && (
          <KvCallout tone="danger">
            <p>{error}</p>
          </KvCallout>
        )}
      </section>

      {result && (
        <section className="space-y-3" aria-label="Check result">
          <KvSectionHeader
            icon={result.verdict === "usable" ? Check : X}
            title={result.verdict === "usable" ? "Clip looks usable" : "Clip is not usable"}
          />
          <p className="text-sm text-fg-2">
            {result.duration_seconds} seconds · {result.resolution} · {result.frames_sampled} frames
            sampled · confidence: {result.confidence}
          </p>
          <ul className="space-y-1 text-sm">
            {result.checks.map((check) => (
              <li key={check.name} className="flex flex-wrap gap-2">
                {check.passed ? (
                  <Check size={15} className="text-ok" aria-label="passed" />
                ) : (
                  <X size={15} className="text-danger" aria-label="failed" />
                )}
                <span className="font-semibold">{check.name}</span>
                <span className="text-fg-2">
                  {check.value} — {check.detail}
                </span>
              </li>
            ))}
          </ul>
          {result.reasons.length > 0 && (
            <ul className="space-y-1 text-sm text-danger">
              {result.reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
          <KvCallout tone="info">
            <p>
              <strong>{result.label}</strong> {result.limits}
            </p>
          </KvCallout>
        </section>
      )}
    </div>
  );
}
