"use client";

/**
 * Motion Primitives–style building blocks, implemented on top of `motion`.
 * TextEffect, AnimatedGroup, InView, AnimatedNumber, TextLoop, TextShimmer,
 * Magnetic, Tilt, Spotlight, ScrollProgress, Disclosure, MorphingDialog, Dock.
 */

import {
  AnimatePresence,
  animate,
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
  type Variants,
} from "motion/react";
import { X } from "lucide-react";
import React, { createContext, useContext, useEffect, useId, useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";

/* ------------------------------------------------------------------ */
/* TextEffect: per-word / per-char reveal                              */
/* ------------------------------------------------------------------ */
export function TextEffect({
  children,
  per = "word",
  delay = 0,
  className,
  as: Tag = "p",
  preset = "fade-in-blur",
}: {
  children: string;
  per?: "word" | "char";
  delay?: number;
  className?: string;
  as?: keyof React.JSX.IntrinsicElements;
  preset?: "fade-in-blur" | "slide" | "scale";
}) {
  const reduce = useReducedMotion();
  const segments = per === "word" ? children.split(/(\s+)/) : Array.from(children);
  const item: Variants = {
    hidden:
      preset === "slide"
        ? { opacity: 0, y: 16 }
        : preset === "scale"
          ? { opacity: 0, scale: 0.8 }
          : { opacity: 0, y: 8, filter: "blur(10px)" },
    visible: { opacity: 1, y: 0, scale: 1, filter: "blur(0px)", transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] } },
  };
  const M = motion.create(Tag as "p");
  if (reduce) return <Tag className={className}>{children}</Tag>;
  return (
    <M
      className={className}
      initial="hidden"
      animate="visible"
      variants={{ visible: { transition: { staggerChildren: per === "word" ? 0.06 : 0.02, delayChildren: delay } } }}
      aria-label={children}
    >
      {segments.map((seg, i) =>
        seg.trim() === "" ? (
          <span key={i}>{seg}</span>
        ) : (
          <motion.span key={i} className="inline-block" variants={item}>
            {seg}
          </motion.span>
        ),
      )}
    </M>
  );
}

/* ------------------------------------------------------------------ */
/* AnimatedGroup: staggered children                                    */
/* ------------------------------------------------------------------ */
export function AnimatedGroup({
  children,
  className,
  stagger = 0.08,
  delay = 0,
  preset = "blur-slide",
}: {
  children: React.ReactNode;
  className?: string;
  stagger?: number;
  delay?: number;
  preset?: "blur-slide" | "scale" | "fade";
}) {
  const item: Variants = {
    hidden: preset === "scale" ? { opacity: 0, scale: 0.92 } : preset === "fade" ? { opacity: 0 } : { opacity: 0, y: 18, filter: "blur(8px)" },
    visible: { opacity: 1, y: 0, scale: 1, filter: "blur(0px)", transition: { duration: 0.55, ease: [0.22, 1, 0.36, 1] } },
  };
  return (
    <motion.div
      className={className}
      initial="hidden"
      animate="visible"
      variants={{ visible: { transition: { staggerChildren: stagger, delayChildren: delay } } }}
    >
      {React.Children.map(children, (child, i) => (
        <motion.div key={i} variants={item}>
          {child}
        </motion.div>
      ))}
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/* InView: animate when scrolled into view                              */
/* ------------------------------------------------------------------ */
export function InView({
  children,
  className,
  once = true,
  delay = 0,
}: {
  children: React.ReactNode;
  className?: string;
  once?: boolean;
  delay?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once, margin: "0px 0px -10% 0px" });
  return (
    <motion.div
      ref={ref}
      className={className}
      initial={{ opacity: 0, y: 24, filter: "blur(6px)" }}
      animate={inView ? { opacity: 1, y: 0, filter: "blur(0px)" } : {}}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1], delay }}
    >
      {children}
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/* AnimatedNumber: spring count-up                                      */
/* ------------------------------------------------------------------ */
export function AnimatedNumber({
  value,
  format = (v) => Math.round(v).toString(),
  className,
}: {
  value: number;
  format?: (v: number) => string;
  className?: string;
}) {
  const mv = useMotionValue(0);
  const spring = useSpring(mv, { stiffness: 90, damping: 20, mass: 0.6 });
  const [text, setText] = useState(format(0));
  useEffect(() => {
    mv.set(value);
  }, [value, mv]);
  useEffect(() => spring.on("change", (v) => setText(format(v))), [spring, format]);
  return <span className={cn("tabular-nums", className)}>{text}</span>;
}

/* ------------------------------------------------------------------ */
/* TextLoop: cycles through lines                                       */
/* ------------------------------------------------------------------ */
export function TextLoop({ items, interval = 1800, className }: { items: string[]; interval?: number; className?: string }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((x) => (x + 1) % items.length), interval);
    return () => clearInterval(t);
  }, [items.length, interval]);
  return (
    <span className={cn("relative inline-block h-[1.5em] overflow-hidden align-bottom", className)}>
      <AnimatePresence mode="popLayout" initial={false}>
        <motion.span
          key={i}
          className="inline-block"
          initial={{ y: 20, opacity: 0, filter: "blur(4px)" }}
          animate={{ y: 0, opacity: 1, filter: "blur(0px)" }}
          exit={{ y: -20, opacity: 0, filter: "blur(4px)" }}
          transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
        >
          {items[i]}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

export function TextShimmer({ children, className }: { children: string; className?: string }) {
  return <span className={cn("text-shimmer", className)}>{children}</span>;
}

/* ------------------------------------------------------------------ */
/* Magnetic: element follows cursor slightly                            */
/* ------------------------------------------------------------------ */
export function Magnetic({ children, strength = 0.35, className }: { children: React.ReactNode; strength?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const x = useSpring(0, { stiffness: 200, damping: 15 });
  const y = useSpring(0, { stiffness: 200, damping: 15 });
  const reduce = useReducedMotion();
  return (
    <motion.div
      ref={ref}
      className={cn("inline-block", className)}
      style={{ x, y }}
      onMouseMove={(e) => {
        if (reduce || !ref.current) return;
        const r = ref.current.getBoundingClientRect();
        x.set((e.clientX - (r.left + r.width / 2)) * strength);
        y.set((e.clientY - (r.top + r.height / 2)) * strength);
      }}
      onMouseLeave={() => {
        x.set(0);
        y.set(0);
      }}
    >
      {children}
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/* Tilt: 3D hover tilt                                                  */
/* ------------------------------------------------------------------ */
export function Tilt({ children, className, max = 6 }: { children: React.ReactNode; className?: string; max?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const rx = useSpring(0, { stiffness: 250, damping: 20 });
  const ry = useSpring(0, { stiffness: 250, damping: 20 });
  const reduce = useReducedMotion();
  return (
    <motion.div
      ref={ref}
      className={className}
      style={{ rotateX: rx, rotateY: ry, transformStyle: "preserve-3d", perspective: 1000 }}
      onMouseMove={(e) => {
        if (reduce || !ref.current) return;
        const r = ref.current.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width - 0.5;
        const py = (e.clientY - r.top) / r.height - 0.5;
        ry.set(px * max * 2);
        rx.set(-py * max * 2);
      }}
      onMouseLeave={() => {
        rx.set(0);
        ry.set(0);
      }}
    >
      {children}
    </motion.div>
  );
}

/* ------------------------------------------------------------------ */
/* Spotlight: cursor-following radial highlight over a container         */
/* ------------------------------------------------------------------ */
export function Spotlight({ className, size = 420 }: { className?: string; size?: number }) {
  const x = useSpring(-1000, { stiffness: 120, damping: 25 });
  const y = useSpring(-1000, { stiffness: 120, damping: 25 });
  const bg = useTransform([x, y], ([px, py]) => `radial-gradient(${size}px circle at ${px}px ${py}px, rgba(0,212,170,0.16), transparent 70%)`);
  useEffect(() => {
    const move = (e: MouseEvent) => {
      x.set(e.clientX);
      y.set(e.clientY);
    };
    window.addEventListener("mousemove", move);
    return () => window.removeEventListener("mousemove", move);
  }, [x, y]);
  return <motion.div aria-hidden className={cn("pointer-events-none fixed inset-0 z-0", className)} style={{ background: bg }} />;
}

/* ------------------------------------------------------------------ */
/* ScrollProgress                                                       */
/* ------------------------------------------------------------------ */
export function ScrollProgress() {
  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, { stiffness: 200, damping: 30 });
  return <motion.div className="fixed left-0 top-0 z-50 h-[2px] w-full origin-left bg-accent" style={{ scaleX }} />;
}

/* ------------------------------------------------------------------ */
/* Disclosure: height-animated expand                                   */
/* ------------------------------------------------------------------ */
export function Disclosure({
  open,
  children,
  className,
}: {
  open: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          className={cn("overflow-hidden", className)}
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/* ------------------------------------------------------------------ */
/* MorphingDialog: card morphs into a modal (shared layoutId)           */
/* ------------------------------------------------------------------ */
const DialogCtx = createContext<{ open: boolean; setOpen: (v: boolean) => void; id: string } | null>(null);

export function MorphingDialog({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open]);
  const ctx = useMemo(() => ({ open, setOpen, id }), [open, id]);
  return <DialogCtx.Provider value={ctx}>{children}</DialogCtx.Provider>;
}

export function MorphingDialogTrigger({ children, className }: { children: React.ReactNode; className?: string }) {
  const ctx = useContext(DialogCtx)!;
  return (
    <motion.div
      layoutId={`dlg-${ctx.id}`}
      role="button"
      tabIndex={0}
      className={cn("cursor-pointer", className)}
      onClick={() => ctx.setOpen(true)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && ctx.setOpen(true)}
      whileHover={{ y: -2 }}
      transition={{ type: "spring", stiffness: 300, damping: 26 }}
    >
      {children}
    </motion.div>
  );
}

export function MorphingDialogContent({ children, className, title }: { children: React.ReactNode; className?: string; title?: string }) {
  const ctx = useContext(DialogCtx)!;
  return (
    <AnimatePresence>
      {ctx.open && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => ctx.setOpen(false)}
          />
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-8" onClick={() => ctx.setOpen(false)}>
            <motion.div
              layoutId={`dlg-${ctx.id}`}
              role="dialog"
              aria-modal="true"
              aria-label={title}
              className={cn(
                "relative max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-[var(--radius-lg)] bg-panel p-6 shadow-[var(--shadow-lg)] ring-1 ring-white/10 sm:p-8",
                className,
              )}
              transition={{ type: "spring", stiffness: 260, damping: 28 }}
              onClick={(e) => e.stopPropagation()}
            >
              <button
                aria-label="Close"
                onClick={() => ctx.setOpen(false)}
                className="absolute right-4 top-4 rounded-full bg-bg-3 p-2 text-fg-2 transition hover:bg-bg-4 hover:text-fg"
              >
                <X size={16} />
              </button>
              {children}
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
}

/* ------------------------------------------------------------------ */
/* Dock: magnifying bottom navigation                                   */
/* ------------------------------------------------------------------ */
export function Dock({
  items,
  active,
  onSelect,
}: {
  items: { id: string; label: string; icon: React.ReactNode }[];
  active: string;
  onSelect: (id: string) => void;
}) {
  const mouseX = useMotionValue(Infinity);
  return (
    <motion.nav
      aria-label="Primary"
      onMouseMove={(e) => mouseX.set(e.clientX)}
      onMouseLeave={() => mouseX.set(Infinity)}
      className="fixed bottom-5 left-1/2 z-40 flex -translate-x-1/2 items-end gap-2 rounded-[var(--radius-pill)] bg-panel/90 px-3 py-2 shadow-[var(--shadow-lg)] ring-1 ring-white/10 backdrop-blur-md"
    >
      {items.map((it) => (
        <DockItem key={it.id} mouseX={mouseX} active={active === it.id} onClick={() => onSelect(it.id)} label={it.label}>
          {it.icon}
        </DockItem>
      ))}
    </motion.nav>
  );
}

function DockItem({
  mouseX,
  children,
  active,
  onClick,
  label,
}: {
  mouseX: ReturnType<typeof useMotionValue<number>>;
  children: React.ReactNode;
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const dist = useTransform(mouseX, (v) => {
    const r = ref.current?.getBoundingClientRect() ?? { x: 0, width: 0 };
    return v - r.x - r.width / 2;
  });
  const size = useSpring(useTransform(dist, [-120, 0, 120], [44, 60, 44]), { stiffness: 200, damping: 14 });
  return (
    <motion.button
      ref={ref}
      style={{ width: size, height: size }}
      onClick={onClick}
      aria-label={label}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group relative flex items-center justify-center rounded-full transition-colors",
        active ? "bg-accent text-black" : "bg-bg-3 text-fg-2 hover:bg-bg-4 hover:text-fg",
      )}
    >
      {children}
      <span className="pointer-events-none absolute -top-9 whitespace-nowrap rounded-md bg-bg-4 px-2 py-1 text-xs text-fg opacity-0 shadow transition group-hover:opacity-100">
        {label}
      </span>
    </motion.button>
  );
}

/* ------------------------------------------------------------------ */
/* ProgressRing (readiness)                                             */
/* ------------------------------------------------------------------ */
export function ProgressRing({ value, size = 96, stroke = 8, label }: { value: number; size?: number; stroke?: number; label?: string }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const mv = useMotionValue(0);
  const offset = useTransform(mv, (v) => c - (v / 100) * c);
  useEffect(() => {
    const ctrl = animate(mv, value, { duration: 1.1, ease: [0.22, 1, 0.36, 1] });
    return ctrl.stop;
  }, [value, mv]);
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="#2a2a2a" strokeWidth={stroke} fill="none" />
        <motion.circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke="var(--color-accent-primary)"
          strokeWidth={stroke}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={c}
          style={{ strokeDashoffset: offset }}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <AnimatedNumber value={value} className="text-xl font-semibold" format={(v) => `${Math.round(v)}%`} />
        {label && <span className="text-[10px] uppercase tracking-wider text-fg-3">{label}</span>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Checkmark that draws in                                              */
/* ------------------------------------------------------------------ */
export function DrawnCheck({ size = 18, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className} aria-hidden>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.3" strokeWidth="2" />
      <path d="M7 12.5l3 3 7-7" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="check-draw" />
    </svg>
  );
}
