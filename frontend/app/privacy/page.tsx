import type { Metadata } from "next";

export const metadata: Metadata = { title: "Privacy — Career Guidance AI" };

/**
 * Privacy policy. Business name and contact are placeholders the owner
 * fills in before announcing paid plans (see SELLING.md go-live list).
 */
export default function Page() {
  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-12">
      <h1 className="font-serif text-4xl">Privacy Policy</h1>
      <p className="mt-2 text-sm text-fg-2">Last updated: October 2026.</p>
      <div className="mt-8 space-y-6 text-sm leading-relaxed text-fg-2">
        <section>
          <h2 className="font-serif text-xl text-white">What we collect</h2>
          <p className="mt-2">
            Account details (email, name, sign-in provider), your profile (skills,
            interests, education, experience), your recommendation runs, plans, progress
            and feedback. Payment processing is handled by Razorpay; we store only the
            order reference, plan, amount and status — never card or bank details.
          </p>
        </section>
        <section>
          <h2 className="font-serif text-xl text-white">How we use it</h2>
          <p className="mt-2">
            To run the Service for you: matching, roadmaps, history and support. We do
            not sell your data and do not use it for advertising. Aggregated, anonymous
            statistics (for example, which careers are explored most) may be used to
            improve the Service.
          </p>
        </section>
        <section>
          <h2 className="font-serif text-xl text-white">AI features</h2>
          <p className="mt-2">
            Optional AI features, when enabled, may send your skills and interests to an
            AI provider to generate explanations. They are labelled as AI-generated and
            are never presented as verified facts. The core matching engine runs locally
            on our own catalogue.
          </p>
        </section>
        <section>
          <h2 className="font-serif text-xl text-white">Your rights</h2>
          <p className="mt-2">
            Export everything or delete your account from Settings at any time; deletion
            removes your runs, plans and progress. Questions: [Contact email].
          </p>
        </section>
      </div>
    </main>
  );
}
