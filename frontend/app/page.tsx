/**
 * Public root: the landing page for anonymous visitors.
 *
 * This page is a server component on purpose: the landing copy is rendered
 * into the static HTML (search engines and no-JS visitors see the pitch).
 * Signed-in visitors are redirected by the <SignedInRedirect /> island.
 * The old tabbed app shell still lives at /classic.
 */
import { LandingView } from "@/components/landing-view";
import { SignedInRedirect } from "@/components/signed-in-redirect";

export default function Page() {
  return (
    <>
      <SignedInRedirect />
      <LandingView />
    </>
  );
}
