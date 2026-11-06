import { Card } from "./card";
export function EmptyState({ title, hint, action }: { title: string; hint: string; action?: React.ReactNode }) {
  return <Card className="text-center"><p className="font-serif text-xl">{title}</p><p className="mx-auto mt-2 max-w-md text-sm text-fg-2">{hint}</p>{action && <div className="mt-4 flex justify-center">{action}</div>}</Card>;
}
