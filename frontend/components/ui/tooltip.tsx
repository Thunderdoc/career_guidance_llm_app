export function Tooltip({ text, children }: { text: string; children: React.ReactNode }) {
  return <span className="group relative inline-flex">{children}<span role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 z-40 mb-2 hidden w-48 -translate-x-1/2 rounded-lg bg-white px-2 py-1 text-center text-xs text-black group-hover:block">{text}</span></span>;
}
