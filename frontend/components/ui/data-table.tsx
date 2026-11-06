export function DataTable({ columns, rows }: { columns: string[]; rows: React.ReactNode[][] }) {
  return (
    <div className="overflow-x-auto"><table className="w-full text-left text-sm">
      <thead><tr>{columns.map((c) => <th key={c} className="border-b border-white/10 px-3 py-2 font-medium text-fg-2">{c}</th>)}</tr></thead>
      <tbody>{rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j} className="border-b border-white/5 px-3 py-2">{cell}</td>)}</tr>)}</tbody>
    </table></div>
  );
}
