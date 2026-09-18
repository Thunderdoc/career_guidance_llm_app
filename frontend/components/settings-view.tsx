"use client";

/**
 * `/settings` — account details, language, data export (JSON + PDF) and the
 * destructive actions. Everything here talks to the signed-in user's own
 * endpoints; no admin surface is exposed.
 */

import { useState } from "react";
import { Download, FileText, LogOut, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { auth, downloadFile, pathway as pathwayApi } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { LOCALES, useI18n } from "@/lib/i18n";
import { TextEffect } from "./motion";
import { Badge, Button, Card, Field, SourceLabel, Spinner, inputCls } from "./ui";

export function SettingsView() {
  const { t, locale, setLocale } = useI18n();
  const { user, logout } = useAuth();
  const router = useRouter();
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!user) return <Spinner label={t("st_title")} />;

  async function handleExport() {
    setBusy(true);
    setError(null);
    try {
      const payload = await auth.exportData();
      downloadFile("career-guidance-data.json", JSON.stringify(payload, null, 2), "application/json");
      setMessage(t("st_saved"));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (confirm !== "DELETE") return;
    setBusy(true);
    setError(null);
    try {
      await auth.deleteMe();
      await logout();
      router.push("/login");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <header>
        <TextEffect as="h1" className="font-serif text-3xl sm:text-4xl">
          {t("st_title")}
        </TextEffect>
        <p className="mt-1 text-sm text-fg-2">{t("st_sub")}</p>
      </header>

      {error && <p className="text-sm text-danger">{error}</p>}
      {message && <p className="text-sm text-ok">{message}</p>}

      <Card>
        <h2 className="font-serif text-xl">{t("st_account")}</h2>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs uppercase tracking-wide text-fg-3">{t("st_email")}</dt>
            <dd>{user.email ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-fg-3">{t("st_provider")}</dt>
            <dd>{user.provider ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-fg-3">{t("st_role")}</dt>
            <dd>
              <Badge tone={user.is_admin ? "accent" : "muted"}>{user.is_admin ? "admin" : "user"}</Badge>
            </dd>
          </div>
        </dl>
        <SourceLabel text={t("st_source")} />
      </Card>

      <Card>
        <h2 className="font-serif text-xl">{t("st_language")}</h2>
        <div className="mt-3 max-w-xs">
          <Field label={t("st_language")}>
            <select value={locale} onChange={(event) => setLocale(event.target.value as typeof locale)} className={inputCls}>
              {LOCALES.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </Card>

      <Card className="flex flex-col gap-3">
        <h2 className="font-serif text-xl">{t("st_data")}</h2>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void handleExport()} disabled={busy}>
            <Download size={15} /> {t("st_export")}
          </Button>
          <a href={pathwayApi.reportUrl()} target="_blank" rel="noreferrer">
            <Button variant="outline" type="button">
              <FileText size={15} /> {t("st_report")}
            </Button>
          </a>
          <Button
            variant="ghost"
            onClick={async () => {
              await logout();
              router.push("/login");
            }}
          >
            <LogOut size={15} /> {t("nav_logout")}
          </Button>
        </div>
        <SourceLabel text={t("st_source")} />
      </Card>

      <Card className="border-danger/30">
        <h2 className="font-serif text-xl text-danger">{t("st_delete")}</h2>
        <p className="mt-1 text-sm text-fg-2">{t("st_delete_warn")}</p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <div className="w-full max-w-xs">
            <Field label={t("st_confirm")}>
              <input value={confirm} onChange={(event) => setConfirm(event.target.value)} className={inputCls} />
            </Field>
          </div>
          <Button variant="danger" onClick={() => void handleDelete()} disabled={confirm !== "DELETE" || busy}>
            <Trash2 size={15} /> {t("st_delete")}
          </Button>
        </div>
      </Card>
    </div>
  );
}
