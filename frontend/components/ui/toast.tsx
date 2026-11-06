"use client";
import { useEffect } from "react";
export function Toast({ message, onDone }: { message: string; onDone?: () => void }) {
  useEffect(() => { const id = setTimeout(() => onDone?.(), 4000); return () => clearTimeout(id); }, [onDone]);
  if (!message) return null;
  return <div role="status" className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-xl bg-white px-4 py-3 text-sm font-medium text-black shadow-lg">{message}</div>;
}
