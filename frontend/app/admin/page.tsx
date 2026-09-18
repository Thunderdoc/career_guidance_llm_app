import type { Metadata } from "next";
import { AdminStandalone } from "@/components/admin-standalone";

export const metadata: Metadata = { title: "Admin — Career Guidance AI" };

export default function Page() {
  return <AdminStandalone />;
}
