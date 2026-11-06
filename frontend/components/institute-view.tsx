"use client";

/**
 * Phase 4 — Institute portal: create/claim, members + invites (list & CSV
 * with per-row errors), seat usage, aggregate cohort with simple bars,
 * needs-attention list and the counsellor review queue. Students see a
 * small "My institute" block with their counsellor review status.
 * Cohort data is aggregate-only here — no student e-mails are shown.
 */

import { useState } from "react";
import {
  institutesApi,
  type Cohort,
  type InstituteMember,
  type InviteReport,
  type ReviewQueueItem,
  type SeatUsage,
} from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useApi } from "@/lib/use-api";
import { Badge, Button, Card, Empty, ErrorNote, Field, Progress, Spinner, inputCls } from "./ui";

function Bars({ items }: { items: { label: string; count: number }[] }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <div className="space-y-2">
      {items.map((i) => (
        <Progress key={i.label} percent={Math.round((i.count / max) * 100)} label={`${i.label} — ${i.count}`} />
      ))}
      {items.length === 0 && <p className="text-sm text-fg-2">—</p>}
    </div>
  );
}

function InviteReportView({ report }: { report: InviteReport }) {
  return (
    <ul className="mt-3 space-y-1 text-sm">
      {report.results.map((r) => (
        <li key={`${r.row}-${r.email}`} className={r.status === "error" ? "text-red-300" : "text-fg-2"}>
          {r.row}. {r.email} — {r.status}
          {r.error ? `: ${r.error}` : ""}
        </li>
      ))}
    </ul>
  );
}

export function InstituteView() {
  const { t } = useI18n();
  const mine = useApi(() => institutesApi.mine(), []);
  const [name, setName] = useState("");
  const [accent, setAccent] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [note, setNote] = useState("");
  const institute = mine.data?.institute ?? null;
  const myRole = mine.data?.my_role ?? "";
  const staff = myRole === "institute_admin" || myRole === "counsellor";

  const staffData = useApi(
    async () => {
      if (!institute || !staff) return null;
      const [m, c, q] = await Promise.all([
        institutesApi.members(institute.id),
        institutesApi.cohort(institute.id),
        institutesApi.reviewQueue(institute.id),
      ]);
      return { members: m.members, seatUsage: m.seat_usage, cohort: c.cohort, queue: q.queue };
    },
    [institute?.id, staff],
  );
  const myReviews = useApi(
    async () => (institute && !staff ? (await institutesApi.myReviews()).reviews : []),
    [institute?.id, staff],
  );

  if (mine.loading && !mine.data) return <Spinner label={t("p4_title")} />;
  if (mine.error) return <ErrorNote error={mine.error} retry={mine.reload} />;

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setActionError("");
    try {
      await fn();
      await mine.reload();
      await staffData.reload();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const roleLabel = (role: string) =>
    role === "counsellor" ? t("p4_role_counsellor") : role === "institute_admin" ? t("p4_role_admin") : t("p4_role_student");

  return (
    <div className="space-y-6">
      <h2 className="font-serif text-2xl">{t("p4_title")}</h2>
      {actionError && <ErrorNote error={actionError} />}
      {note && <p className="text-sm text-fg-2">{note}</p>}

      {!institute && (
        <Card>
          <p className="text-sm text-fg-2">{t("p4_none")}</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <Field label={t("p4_name")}>
              <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label={t("p4_accent")}>
              <input className={inputCls} value={accent} onChange={(e) => setAccent(e.target.value)} placeholder="#0f766e" />
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <Button disabled={busy || name.trim().length < 2} onClick={() => act(async () => {
              await institutesApi.create({ name: name.trim(), accent_color: accent.trim() });
            })}>{t("p4_create")}</Button>
            <Button variant="outline" disabled={busy} onClick={() => act(async () => {
              await institutesApi.claim();
              setNote(t("p4_claimed"));
            })}>{t("p4_claim")}</Button>
          </div>
        </Card>
      )}

      {institute && (
        <>
          <Card>
            <div className="flex flex-wrap items-center gap-3">
              <h3 className="text-lg font-medium">{t("p4_my_institute")}: {institute.name}</h3>
              <Badge tone="accent">{roleLabel(myRole)}</Badge>
              {institute.accent_color && (
                <span className="inline-block h-4 w-4 rounded-full" style={{ background: institute.accent_color }} />
              )}
            </div>
            {mine.data?.seat_usage && (
              <p className="mt-2 text-sm text-fg-2">
                {t("p4_seats", { used: mine.data.seat_usage.seats_used, limit: mine.data.seat_usage.seat_limit })}
              </p>
            )}
            {!staff && (myReviews.data ?? []).length > 0 && (
              <ul className="mt-3 space-y-2 text-sm">
                {(myReviews.data ?? []).map((r) => (
                  <li key={r.run_id}>
                    <Badge tone="ok">{t("p4_reviewed_by")}</Badge>{" "}
                    <span className="text-fg-2">{r.counsellor_review.note}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {staff && staffData.data && (
            <StaffSections
              instituteId={institute.id}
              members={staffData.data.members}
              seatUsage={staffData.data.seatUsage}
              cohort={staffData.data.cohort}
              queue={staffData.data.queue}
              isAdmin={myRole === "institute_admin"}
              busy={busy}
              act={act}
              roleLabel={roleLabel}
            />
          )}
          {staff && staffData.loading && !staffData.data && <Spinner label={t("p4_cohort")} />}
          {staff && staffData.error && <ErrorNote error={staffData.error} retry={staffData.reload} />}
        </>
      )}
    </div>
  );
}

function StaffSections(props: {
  instituteId: number;
  members: InstituteMember[];
  seatUsage: SeatUsage;
  cohort: Cohort;
  queue: ReviewQueueItem[];
  isAdmin: boolean;
  busy: boolean;
  act: (fn: () => Promise<unknown>) => Promise<void>;
  roleLabel: (role: string) => string;
}) {
  const { t } = useI18n();
  const [inviteText, setInviteText] = useState("");
  const [report, setReport] = useState<InviteReport | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const { cohort } = props;

  async function sendInvites() {
    const members = inviteText
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [email, role] = line.split(",").map((s) => s.trim());
        return { email, role: role || "student" };
      });
    if (!members.length) return;
    await props.act(async () => setReport(await institutesApi.invite(props.instituteId, members)));
  }

  return (
    <>
      <Card>
        <h3 className="text-lg font-medium">{t("p4_members")}</h3>
        <p className="mt-1 text-sm text-fg-2">
          {t("p4_seats", { used: props.seatUsage.seats_used, limit: props.seatUsage.seat_limit })}
        </p>
        <ul className="mt-3 space-y-2 text-sm">
          {props.members.map((m) => (
            <li key={m.user_id} className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{m.name || m.email}</span>
              <Badge>{props.roleLabel(m.institute_role)}</Badge>
              {props.isAdmin && m.institute_role !== "institute_admin" && (
                <Button variant="ghost" disabled={props.busy} onClick={() =>
                  props.act(async () => { await institutesApi.removeMember(props.instituteId, m.user_id); })
                }>{t("p4_remove")}</Button>
              )}
            </li>
          ))}
        </ul>
        {props.isAdmin && (
          <div className="mt-5 space-y-3">
            <Field label={t("p4_invite")}>
              <textarea className={inputCls} rows={3} value={inviteText} onChange={(e) => setInviteText(e.target.value)} placeholder={t("p4_invite_ph")} />
            </Field>
            <div className="flex flex-wrap items-center gap-3">
              <Button disabled={props.busy} onClick={sendInvites}>{t("p4_invite_send")}</Button>
              <label className="text-sm text-fg-2">
                {t("p4_invite_csv")}
                <input
                  type="file"
                  accept=".csv,text/csv"
                  className="ml-2 text-sm"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void props.act(async () => setReport(await institutesApi.inviteCsv(props.instituteId, file)));
                  }}
                />
              </label>
            </div>
            {report && <InviteReportView report={report} />}
          </div>
        )}
      </Card>

      <Card>
        <h3 className="text-lg font-medium">{t("p4_cohort")}</h3>
        <div className="mt-4 grid gap-6 md:grid-cols-3">
          <div><h4 className="mb-2 text-sm font-medium">{t("p4_top_careers")}</h4>
            <Bars items={cohort.top_recommended_careers.map((c) => ({ label: c.title, count: c.count }))} /></div>
          <div><h4 className="mb-2 text-sm font-medium">{t("p4_missing_skills")}</h4>
            <Bars items={cohort.most_missing_skills.map((s) => ({ label: s.skill, count: s.count }))} /></div>
          <div><h4 className="mb-2 text-sm font-medium">{t("p4_readiness")}</h4>
            <Bars items={cohort.readiness_distribution.map((b) => ({ label: `${b.bucket}%`, count: b.count }))} /></div>
        </div>
        <h4 className="mt-6 text-sm font-medium">{t("p4_attention")}</h4>
        {cohort.needs_attention.length === 0 ? (
          <p className="mt-2 text-sm text-fg-2">{t("p4_attention_none")}</p>
        ) : (
          <ul className="mt-2 space-y-1 text-sm">
            {cohort.needs_attention.map((a) => (
              <li key={a.user_id}>{a.name || a.user_id} — {a.reasons.join(", ")}</li>
            ))}
          </ul>
        )}
        <div className="mt-5 flex gap-3">
          <a className="text-sm underline" href={institutesApi.reportUrl(props.instituteId, "csv")}>{t("p4_export_csv")}</a>
          <a className="text-sm underline" href={institutesApi.reportUrl(props.instituteId, "pdf")}>{t("p4_export_pdf")}</a>
        </div>
      </Card>

      <Card>
        <h3 className="text-lg font-medium">{t("p4_review_queue")}</h3>
        {props.queue.length === 0 && <Empty title={t("p4_review_queue")} hint={t("p4_attention_none")} />}
        <ul className="mt-3 space-y-3 text-sm">
          {props.queue.map((q) => (
            <li key={q.run_id} className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{q.student_name}</span>
                <span className="text-fg-2">{q.top_career} · {q.created_at.slice(0, 10)}</span>
                {q.reviewed && <Badge tone="ok">{t("p4_reviewed_by")}</Badge>}
              </div>
              <div className="flex flex-wrap gap-2">
                <input
                  className={inputCls}
                  placeholder={t("p4_review_note")}
                  value={notes[q.run_id] ?? ""}
                  onChange={(e) => setNotes({ ...notes, [q.run_id]: e.target.value })}
                />
                <Button disabled={props.busy} onClick={() =>
                  props.act(async () => {
                    await institutesApi.reviewRun(props.instituteId, q.run_id, {
                      note: notes[q.run_id] ?? "", approved: true,
                    });
                  })
                }>{t("p4_review_approve")}</Button>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}
