"use client";

/**
 * Type-ahead career picker backed by `/api/v1/careers/search`.
 * Debounced, keyboard friendly and dependency-free.
 */

import { useEffect, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";

type Hit = { id: string; title: string; job_zone: number };

export function CareerPicker({
  value,
  onChange,
  label,
  placeholder,
  className,
}: {
  value: string;
  onChange: (id: string) => void;
  label?: string;
  placeholder?: string;
  className?: string;
}) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setHits([]);
      return;
    }
    let active = true;
    const timer = window.setTimeout(async () => {
      setLoading(true);
      try {
        const payload = await api.searchCareers(trimmed, 8);
        if (active) setHits(payload.results);
      } catch {
        if (active) setHits([]);
      } finally {
        if (active) setLoading(false);
      }
    }, 220);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [query]);

  useEffect(() => {
    function onClick(event: MouseEvent) {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  return (
    <div ref={box} className={cn("relative", className)}>
      <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-bg-3/60 px-3 py-2 focus-within:border-accent/50">
        <Search size={15} className="shrink-0 text-fg-3" />
        <input
          value={open ? query : label || ""}
          onChange={(event) => {
            setQuery(event.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            setOpen(true);
            setQuery("");
          }}
          placeholder={placeholder ?? "Search a career…"}
          className="w-full bg-transparent text-sm text-fg outline-none placeholder:text-fg-3"
          aria-label={placeholder ?? "Search careers"}
        />
        {value && (
          <button
            type="button"
            aria-label="Clear"
            onClick={() => {
              onChange("");
              setQuery("");
            }}
            className="text-fg-3 transition hover:text-fg"
          >
            <X size={14} />
          </button>
        )}
      </div>
      {open && (query.trim().length >= 2 || hits.length > 0) && (
        <ul className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-xl border border-white/10 bg-bg-2 py-1 shadow-xl">
          {loading && <li className="px-3 py-2 text-xs text-fg-3">…</li>}
          {!loading && hits.length === 0 && <li className="px-3 py-2 text-xs text-fg-3">No match</li>}
          {hits.map((hit) => (
            <li key={hit.id}>
              <button
                type="button"
                onClick={() => {
                  onChange(hit.id);
                  setOpen(false);
                  setQuery("");
                }}
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm text-fg-2 transition hover:bg-white/5 hover:text-fg"
              >
                <span>{hit.title}</span>
                <span className="text-xs text-fg-3">zone {hit.job_zone}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
