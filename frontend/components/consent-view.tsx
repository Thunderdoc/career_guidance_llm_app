"use client";

/**
 * Phase 5 — Privacy tab inside /account: least-data age declaration,
 * under-18 status, and the parental-consent card (request / status /
 * revoke). Talks only to /api/v1/me/consent* + /me/age-declaration.
 */

import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import { consentApi, type PrivacyStatus } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useI18n, type Key } from "@/lib/i18n";
import { useApi } from "@/lib/use-api";
import { Badge, Button, Card, ErrorNote, Field, Spinner, inputCls } from "./ui";

type TFn = (k: Key, vars?: Record<string, string | number>) => string;

function statusBadge(status: string, t: TFn) {
  const key = `p5_status_${status}` as Key;
  if (status === "granted") return <Badge tone="ok">{t(key)}</Badge>;
  if (status === "pending" || status === "needs_reconsent") return <Badge tone="gold">{t(key)}</Badge>;
  if (status === "denied" || status === "revoked") return <Badge tone="danger">{t(key)}</Badge>;
  return <Badge tone="muted">{t(key)}</Badge>;
}

export function ConsentView() {
  const { t } = useI18n();
  const { refresh } = useAuth();
  const { data, error, loading, reload } = useApi<PrivacyStatus>(() => consentApi.status(), []);
  const [band, setBand] = useState("");
  const [year, setYear] = useState("");
  const [guardian, setGuardian] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [actionError, setActionError] = useState("");
  const [devLink, setDevLink] = useState("");

  if (loading && !data) return <Spinner label={t("p5_consent_title")} />;
  if (error) return <ErrorNote error={error} retry={reload} />;
  if (!data) return null;

  const ageBand = band || data.age_band || "";
  const status = data.consent?.effective_status ?? data.effective_status;

  async function saveAge() {
    setBusy(true);
    setActionError("");
    setNote("");
    try {
      await consentApi.declare({
        age_band: ageBand,
        birth_year: year.trim() ? Number(year.trim()) : (data?.birth_year ?? null),
      });
      setNote(t("p5_saved"));
      await refresh();
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function requestConsent() {
    setBusy(true);
    setActionError("");
    setNote("");
    setDevLink("");
    try {
      const out = await consentApi.requestConsent(guardian.trim());
      setNote(t("p5_request_sent"));
      if (out.consent.dev_link) setDevLink(out.consent.dev_link);
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function revoke() {
    setBusy(true);
    setActionError("");
    try {
      await consentApi.revoke();
      await reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {actionError && <p className="text-sm text-danger">{actionError}</p>}
      {note && <p className="text-sm text-ok">{note}</p>}

      <Card>
        <h2 className="flex items-center gap-2 font-serif text-xl">
          <ShieldCheck size={18} /> {t("p5_age_title")}
        </h2>
        <p className="mt-1 text-sm text-fg-2">{t("p5_age_sub")}</p>
        <div className="mt-3 flex flex-col gap-2">
          {(
            [
              ["adult", "p5_adult"],
              ["minor", "p5_minor"],
            ] as const
          ).map(([value, label]) => (
            <label key={value} className="flex items-center gap-2 text-sm text-fg-2">
              <input
                type="radio"
                name="age-band"
                checked={ageBand === value}
                onChange={() => setBand(value)}
              />
              {t(label)}
            </label>
          ))}
        </div>
        <div className="mt-3 max-w-xs">
          <Field label={t("p5_birth_year")}>
            <input
              className={inputCls}
              inputMode="numeric"
              placeholder={t("p5_birth_year_ph")}
              defaultValue={data.birth_year ?? ""}
              onChange={(e) => setYear(e.target.value)}
            />
          </Field>
        </div>
        <div className="mt-3 flex items-center gap-3">
          <Button onClick={() => void saveAge()} disabled={busy || !ageBand}>
            {t("p5_age_save")}
          </Button>
          <Badge tone={data.is_minor ? "gold" : "muted"}>
            {data.is_minor ? t("p5_minor_status") : t("p5_adult_status")}
          </Badge>
        </div>
      </Card>

      {data.is_minor && (
        <Card>
          <h2 className="font-serif text-xl">{t("p5_consent_title")}</h2>
          <p className="mt-1 text-sm text-fg-2">{t("p5_consent_sub")}</p>
          <div className="mt-3 flex items-center gap-2 text-sm">
            <span className="text-fg-3">{t("p5_consent_status")}:</span>
            {statusBadge(status, t)}
            {data.consent?.guardian_email && <span className="text-fg-2">{data.consent.guardian_email}</span>}
          </div>
          {status !== "granted" && (
            <div className="mt-4 flex flex-wrap items-end gap-3">
              <div className="w-full max-w-xs">
                <Field label={t("p5_guardian_email")}>
                  <input
                    className={inputCls}
                    type="email"
                    placeholder={t("p5_guardian_ph")}
                    value={guardian}
                    onChange={(e) => setGuardian(e.target.value)}
                  />
                </Field>
              </div>
              <Button onClick={() => void requestConsent()} disabled={busy || !guardian.includes("@")}>
                {t("p5_request_btn")}
              </Button>
            </div>
          )}
          {devLink && (
            <p className="mt-3 break-all text-xs text-fg-3">
              {t("p5_dev_link")}:{" "}
              <a className="text-accent underline" href={devLink}>
                {devLink}
              </a>
            </p>
          )}
          {(status === "granted" || status === "pending") && (
            <div className="mt-4">
              <Button variant="ghost" onClick={() => void revoke()} disabled={busy}>
                {t("p5_revoke_btn")}
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
