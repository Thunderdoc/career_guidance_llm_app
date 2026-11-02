import type { Metadata } from "next";

export const metadata: Metadata = { title: "Terms — Career Guidance AI" };

/**
 * Terms of service. Business name and contact are placeholders the owner
 * fills in before announcing paid plans (see SELLING.md go-live list).
 */
export default function Page() {
  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-12">
      <h1 className="font-serif text-4xl">Terms of Service</h1>
      <p className="mt-2 text-sm text-fg-2">Last updated: October 2026.</p>
      <div className="mt-8 space-y-6 text-sm leading-relaxed text-fg-2">
        <section>
          <h2 className="font-serif text-xl text-white">The service</h2>
          <p className="mt-2">
            Career Guidance AI (the “Service”) is operated by [Business name] (“we”, “us”).
            It provides career matching, assessments, learning roadmaps and job-fit analysis
            based on an occupation catalogue and curated market data. Recommendations are
            guidance, not a guarantee of employment, admission or any outcome.
          </p>
        </section>
        <section>
          <h2 className="font-serif text-xl text-white">Accounts</h2>
          <p className="mt-2">
            You need an account to save plans and history. You are responsible for keeping
            your sign-in details private and for activity under your account. We may disable
            accounts that abuse the Service.
          </p>
        </section>
        <section>
          <h2 className="font-serif text-xl text-white">Plans and payment</h2>
          <p className="mt-2">
            Free accounts include career matching, assessments, search and Markdown/JSON
            exports. Pro and Institute plans unlock the roadmap PDF export and the features
            listed on the pricing page. Payments are processed by Razorpay; we never see or
            store your card or bank details. Prices are shown on the pricing page and may
            change with notice; a change never affects a period you have already paid for.
          </p>
        </section>
        <section>
          <h2 className="font-serif text-xl text-white">Your content</h2>
          <p className="mt-2">
            Your profile, skills, runs and plans remain yours. We use them only to run the
            Service for you. You can export everything or delete your account from Settings.
          </p>
        </section>
        <section>
          <h2 className="font-serif text-xl text-white">Contact</h2>
          <p className="mt-2">Questions about these terms: [Contact email].</p>
        </section>
      </div>
    </main>
  );
}
