"use client";

import { AnimatePresence, motion } from "motion/react";
import {
  Activity,
  BookOpen,
  Loader2,
  MessageSquare,
  RefreshCw,
  RotateCcw,
  Save,
  ScrollText,
  Search,
  Shield,
  ShieldOff,
  Trash2,
  UserX,
  UserCheck,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { admin, type AdminOverview, type AdminUser, type Feedback, type ResourceRow } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { cn } from "@/lib/cn";
import { AnimatedNumber, TextEffect } from "./motion";

type Tab = "overview" | "users" | "runs" | "feedback" | "content" | "audit";
const TABS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  { id: "overview", label: "Overview", icon: <Activity size={15} /> },
  { id: "users", label: "Users", icon: <Users size={15} /> },
  { id: "runs", label: "Runs", icon: <ScrollText size={15} /> },
  { id: "feedback", label: "Feedback", icon: <MessageSquare size={15} /> },
  { id: "content", label: "Content", icon: <BookOpen size={15} /> },
  { id: "audit", label: "Audit", icon: <Shield size={15} /> },
];

export function AdminView() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("overview");
  if (!user?.is_admin) {
    return (
      <div className="pt-16 text-center">
        <ShieldOff className="mx-auto text-fg-3" />
        <h1 className="mt-4 font-serif text-3xl">Admin only</h1>
        <p className="mt-2 text-sm text-fg-2">Sign in with an administrator account to open this page.</p>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-6">
      <header className="pt-4">
        <TextEffect as="h1" per="word" className="font-serif text-4xl tracking-tight">
          Admin console
        </TextEffect>
        <p className="mt-1 text-sm text-fg-2">Signed in as {user.email}</p>
      </header>
      <nav className="flex flex-wrap gap-1 rounded-full bg-bg-3 p-1 ring-1 ring-white/5" aria-label="Admin sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn("relative flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs transition", tab === t.id ? "text-black" : "text-fg-2 hover:text-fg")}
          >
            {tab === t.id && <motion.span layoutId="admin-pill" className="absolute inset-0 rounded-full bg-accent" transition={{ type: "spring", stiffness: 400, damping: 32 }} />}
            <span className="relative z-10 flex items-center gap-1.5">
              {t.icon} {t.label}
            </span>
          </button>
        ))}
      </nav>
      <AnimatePresence mode="wait">
        <motion.div key={tab} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2 }}>
          {tab === "overview" && <Overview />}
          {tab === "users" && <UsersTab meId={user.id} />}
          {tab === "runs" && <RunsTab />}
          {tab === "feedback" && <FeedbackTab />}
          {tab === "content" && <ContentTab />}
          {tab === "audit" && <AuditTab />}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

// ----------------------------------------------------------------------------

function useLoad<T>(fn: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const reload = useCallback(async () => {
    setBusy(true);
    try {
      setData(await fn());
      setErr("");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [fn]);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, err, busy, reload };
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <div className={cn("rounded-2xl bg-bg-3 p-4 ring-1 ring-white/5", className)}>{children}</div>;
}

function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <Card>
      <div className="text-[11px] uppercase tracking-wider text-fg-3">{label}</div>
      <div className="mt-1 font-serif text-3xl">
        <AnimatedNumber value={value} />
      </div>
      {hint && <div className="text-xs text-fg-3">{hint}</div>}
    </Card>
  );
}

function Bars({ rows, max }: { rows: [string, number][]; max?: number }) {
  const m = max ?? Math.max(1, ...rows.map((r) => r[1]));
  return (
    <ul className="flex flex-col gap-2">
      {rows.map(([k, v], i) => (
        <li key={k} className="text-xs">
          <div className="flex justify-between">
            <span className="truncate pr-2 text-fg-2">{k}</span>
            <span className="text-fg-3">{v}</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-bg-4">
            <motion.div initial={{ width: 0 }} animate={{ width: `${(100 * v) / m}%` }} transition={{ delay: i * 0.04, duration: 0.5, ease: [0.22, 1, 0.36, 1] }} className="h-full rounded-full bg-accent" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function Overview() {
  const load = useCallback(() => admin.overview(), []);
  const { data: o, err } = useLoad<AdminOverview>(load);
  if (err) return <p className="text-sm text-red-400">{err}</p>;
  if (!o) return <Loader2 className="animate-spin text-fg-3" />;
  const perDay = o.runs.per_day;
  const maxDay = Math.max(1, ...perDay.map((d) => d[1]));
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Users" value={o.users.total} hint={`+${o.users.new_7d} this week · ${o.users.active_7d} active`} />
        <Stat label="Runs" value={o.runs.total} hint={`${o.runs.ai} AI · ${o.runs.demo} offline · ${o.runs.anonymous} anon`} />
        <Stat label="Feedback" value={o.feedback.total} hint={`avg ${o.feedback.avg_rating} ★ · ${o.feedback.open} open`} />
        <Stat label="Occupations" value={o.system.occupations} hint={`v${o.system.version} · ${o.system.ai_mode ? "AI" : "offline"} · up ${Math.round(o.system.uptime_s / 60)}m`} />
      </div>
      <Card>
        <div className="mb-3 text-xs uppercase tracking-wider text-fg-3">Runs per day (30d)</div>
        {perDay.length === 0 ? (
          <p className="text-sm text-fg-3">No runs yet.</p>
        ) : (
          <div className="flex h-28 items-end gap-1">
            {perDay.map(([d, n], i) => (
              <motion.div key={d} title={`${d}: ${n}`} initial={{ height: 0 }} animate={{ height: `${(100 * n) / maxDay}%` }} transition={{ delay: i * 0.02, duration: 0.4 }} className="min-w-[6px] flex-1 rounded-t bg-accent/70 hover:bg-accent" />
            ))}
          </div>
        )}
      </Card>
      <div className="grid gap-3 sm:grid-cols-2">
        <Card>
          <div className="mb-3 text-xs uppercase tracking-wider text-fg-3">Top recommended careers</div>
          <Bars rows={o.top_careers.slice(0, 8)} />
        </Card>
        <Card>
          <div className="mb-3 text-xs uppercase tracking-wider text-fg-3">Most-missing skills</div>
          <Bars rows={o.top_missing_skills.slice(0, 8)} />
        </Card>
      </div>
    </div>
  );
}

function UsersTab({ meId }: { meId: string }) {
  const [q, setQ] = useState("");
  const load = useCallback(() => admin.users(q), [q]);
  const { data, err, reload } = useLoad<{ users: AdminUser[] }>(load);
  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      await reload();
    } catch (e) {
      alert((e as Error).message);
    }
  };
  return (
    <div className="flex flex-col gap-3">
      <SearchBox value={q} onChange={setQ} placeholder="Search e-mail or name" />
      {err && <p className="text-sm text-red-400">{err}</p>}
      <Card className="overflow-x-auto p-0">
        <table className="w-full text-left text-xs">
          <thead className="text-fg-3">
            <tr>
              <th className="px-4 py-3 font-normal">User</th>
              <th className="px-2 py-3 font-normal">Provider</th>
              <th className="px-2 py-3 font-normal">Runs</th>
              <th className="px-2 py-3 font-normal">Last login</th>
              <th className="px-2 py-3 font-normal">Role</th>
              <th className="px-4 py-3 text-right font-normal">Actions</th>
            </tr>
          </thead>
          <tbody>
            {data?.users.map((u) => (
              <tr key={u.id} className={cn("border-t border-white/5", u.disabled && "opacity-50")}>
                <td className="px-4 py-2.5">
                  <div className="font-medium text-fg">{u.name || "—"}</div>
                  <div className="text-fg-3">{u.email}</div>
                </td>
                <td className="px-2 py-2.5 text-fg-2">{u.provider}</td>
                <td className="px-2 py-2.5 text-fg-2">{u.runs}</td>
                <td className="px-2 py-2.5 text-fg-2">{u.last_login_at.slice(0, 10)}</td>
                <td className="px-2 py-2.5">
                  <span className={cn("rounded-full px-2 py-0.5", u.role === "admin" ? "bg-gold/15 text-gold" : "bg-bg-4 text-fg-2")}>{u.role}</span>
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex justify-end gap-1">
                    <IconBtn title={u.role === "admin" ? "Demote to user" : "Promote to admin"} disabled={u.id === meId} onClick={() => act(() => admin.setRole(u.id, u.role === "admin" ? "user" : "admin"))}>
                      {u.role === "admin" ? <ShieldOff size={14} /> : <Shield size={14} />}
                    </IconBtn>
                    <IconBtn title={u.disabled ? "Enable" : "Disable"} disabled={u.id === meId} onClick={() => act(() => admin.setDisabled(u.id, !u.disabled))}>
                      {u.disabled ? <UserCheck size={14} /> : <UserX size={14} />}
                    </IconBtn>
                    <IconBtn title="Delete user and their runs" danger disabled={u.id === meId} onClick={() => confirm(`Delete ${u.email} and all their data?`) && act(() => admin.deleteUser(u.id))}>
                      <Trash2 size={14} />
                    </IconBtn>
                  </div>
                </td>
              </tr>
            ))}
            {data && data.users.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-fg-3">
                  No users found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function RunsTab() {
  const load = useCallback(() => admin.runs(), []);
  const { data, reload } = useLoad(load);
  return (
    <Card className="overflow-x-auto p-0">
      <table className="w-full text-left text-xs">
        <thead className="text-fg-3">
          <tr>
            <th className="px-4 py-3 font-normal">#</th>
            <th className="px-2 py-3 font-normal">When</th>
            <th className="px-2 py-3 font-normal">User</th>
            <th className="px-2 py-3 font-normal">Skills</th>
            <th className="px-2 py-3 font-normal">Top result</th>
            <th className="px-4 py-3 font-normal" />
          </tr>
        </thead>
        <tbody>
          {data?.runs.map((r) => (
            <tr key={r.id} className="border-t border-white/5">
              <td className="px-4 py-2.5 text-fg-3">{r.id}</td>
              <td className="px-2 py-2.5 text-fg-2">{r.created_at.replace("T", " ").slice(0, 16)}</td>
              <td className="px-2 py-2.5 text-fg-3">{r.user_id ? r.user_id.slice(0, 6) : "anon"}</td>
              <td className="max-w-[240px] truncate px-2 py-2.5 text-fg-2">{r.skills}</td>
              <td className="px-2 py-2.5 text-fg">{r.titles[0]}</td>
              <td className="px-4 py-2.5 text-right">
                <IconBtn title="Delete run" danger onClick={() => admin.deleteRun(r.id).then(reload)}>
                  <Trash2 size={14} />
                </IconBtn>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function FeedbackTab() {
  const [status, setStatus] = useState<string>("");
  const load = useCallback(() => admin.feedback(status || undefined), [status]);
  const { data, reload } = useLoad<{ feedback: Feedback[] }>(load);
  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-1">
        {["", "new", "reviewed", "resolved"].map((s) => (
          <button key={s} onClick={() => setStatus(s)} className={cn("rounded-full px-3 py-1 text-xs", status === s ? "bg-accent text-black" : "bg-bg-3 text-fg-2")}>
            {s || "all"}
          </button>
        ))}
      </div>
      <div className="flex flex-col gap-2">
        {data?.feedback.map((f) => (
          <Card key={f.id} className="flex items-start gap-3">
            <div className="text-gold">{"★".repeat(f.rating)}<span className="text-fg-3">{"★".repeat(5 - f.rating)}</span></div>
            <div className="min-w-0 flex-1">
              <div className="text-sm text-fg">{f.comment || <span className="text-fg-3">(no comment)</span>}</div>
              <div className="mt-1 text-[11px] text-fg-3">
                {f.email ?? "anonymous"} · {f.career_title || "general"} · {f.created_at.slice(0, 10)}
              </div>
            </div>
            <select value={f.status} onChange={(e) => admin.setFeedback(f.id, e.target.value).then(reload)} className="rounded-lg bg-bg-4 px-2 py-1 text-xs text-fg">
              <option value="new">new</option>
              <option value="reviewed">reviewed</option>
              <option value="resolved">resolved</option>
            </select>
          </Card>
        ))}
        {data && data.feedback.length === 0 && <p className="text-sm text-fg-3">No feedback yet.</p>}
      </div>
    </div>
  );
}

function ContentTab() {
  const [q, setQ] = useState("");
  const load = useCallback(() => admin.resources(q), [q]);
  const { data, reload } = useLoad<{ skills: ResourceRow[] }>(load);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const rows = useMemo(() => data?.skills ?? [], [data]);

  const startEdit = (r: ResourceRow) => {
    setEditing(r.skill);
    setDraft(JSON.stringify(r.resources, null, 2));
  };
  const save = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await admin.putResources(editing, JSON.parse(draft));
      setEditing(null);
      await reload();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="flex flex-col gap-3">
      <SearchBox value={q} onChange={setQ} placeholder="Filter skills (e.g. python)" />
      <p className="text-xs text-fg-3">Learning resources shown to users, per skill. Overrides are stored in the database and take precedence over data/learning_resources.yaml.</p>
      <div className="flex flex-col gap-2">
        {rows.slice(0, 60).map((r) => (
          <Card key={r.skill} className="p-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm">
                <span className="font-medium">{r.skill}</span>
                {r.overridden && <span className="rounded-full bg-gold/15 px-2 py-0.5 text-[10px] text-gold">override</span>}
                <span className="text-xs text-fg-3">{r.resources.length} resources</span>
              </div>
              <div className="flex gap-1">
                <IconBtn title="Edit" onClick={() => (editing === r.skill ? setEditing(null) : startEdit(r))}>
                  <Save size={14} />
                </IconBtn>
                {r.overridden && (
                  <IconBtn title="Reset to default" onClick={() => admin.resetResources(r.skill).then(reload)}>
                    <RotateCcw size={14} />
                  </IconBtn>
                )}
              </div>
            </div>
            <AnimatePresence>
              {editing === r.skill && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
                  <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={8} className="mt-3 w-full rounded-lg bg-bg-4 p-2 font-mono text-[11px] text-fg focus:outline-none focus:ring-1 focus:ring-accent" />
                  <div className="mt-2 flex justify-end gap-2">
                    <button onClick={() => setEditing(null)} className="rounded-lg px-3 py-1.5 text-xs text-fg-2 hover:bg-bg-4">
                      Cancel
                    </button>
                    <button onClick={save} disabled={saving} className="flex items-center gap-1 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-black">
                      {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} Save
                    </button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            {editing !== r.skill && (
              <ul className="mt-2 flex flex-col gap-0.5 text-xs text-fg-2">
                {r.resources.slice(0, 3).map((x) => (
                  <li key={x.url} className="truncate">
                    <a href={x.url} target="_blank" rel="noreferrer" className="hover:text-accent">
                      {x.title}
                    </a>{" "}
                    <span className="text-fg-3">· {x.provider}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        ))}
      </div>
    </div>
  );
}

function AuditTab() {
  const load = useCallback(() => admin.audit(), []);
  const { data, reload, busy } = useLoad(load);
  return (
    <Card className="p-0">
      <div className="flex items-center justify-between px-4 py-2">
        <span className="text-xs uppercase tracking-wider text-fg-3">Recent admin & login events</span>
        <IconBtn title="Refresh" onClick={reload}>
          <RefreshCw size={14} className={cn(busy && "animate-spin")} />
        </IconBtn>
      </div>
      <ul className="divide-y divide-white/5 text-xs">
        {data?.log.map((l) => (
          <li key={l.id} className="flex gap-3 px-4 py-2">
            <span className="w-32 shrink-0 text-fg-3">{l.created_at.replace("T", " ").slice(0, 16)}</span>
            <span className="w-40 shrink-0 truncate text-fg-2">{l.actor}</span>
            <span className="text-fg">{l.action}</span>
            <span className="truncate text-fg-3">{l.target}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  const [local, setLocal] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => onChange(local), 250);
    return () => clearTimeout(t);
  }, [local, onChange]);
  return (
    <div className="flex items-center gap-2 rounded-xl bg-bg-3 px-3 ring-1 ring-white/5 focus-within:ring-accent">
      <Search size={14} className="text-fg-3" />
      <input value={local} onChange={(e) => setLocal(e.target.value)} placeholder={placeholder} className="w-full bg-transparent py-2 text-sm text-fg placeholder:text-fg-3 focus:outline-none" />
    </div>
  );
}

function IconBtn({ children, title, onClick, danger, disabled }: { children: React.ReactNode; title: string; onClick: () => void; danger?: boolean; disabled?: boolean }) {
  return (
    <button title={title} aria-label={title} onClick={onClick} disabled={disabled} className={cn("rounded-lg p-1.5 text-fg-3 transition hover:bg-bg-4 disabled:opacity-30", danger ? "hover:text-red-400" : "hover:text-fg")}>
      {children}
    </button>
  );
}
