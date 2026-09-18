import { RequireAuth } from "@/components/require-auth";
import { Shell } from "@/components/shell";

/**
 * The product is private: anonymous visitors are redirected to
 * /login?next=/ and never see app content.
 */
export default function Page() {
  return (
    <RequireAuth>
      <Shell />
    </RequireAuth>
  );
}
