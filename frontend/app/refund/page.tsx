import type { Metadata } from "next";

export const metadata: Metadata = { title: "Refunds — Career Guidance AI" };

/**
 * Refund policy. Business name and contact are placeholders the owner
 * fills in before announcing paid plans (see SELLING.md go-live list).
 */
export default function Page() {
  return (
    <main className="mx-auto w-full max-w-2xl px-5 py-12">
      <h1 className="font-serif text-4xl">Refund Policy</h1>
      <p className="mt-2 text-sm text-fg-2">Last updated: October 2026.</p>
      <div className="mt-8 space-y-6 text-sm leading-relaxed text-fg-2">
        <section>
          <h2 className="font-serif text-xl text-white">Free trial</h2>
          <p className="mt-2">
            Pro includes a free trial (length shown on the pricing page). You are only
            charged if you choose to pay after the trial; nothing is charged automatically
            when a trial ends.
          </p>
        </section>
        <section>
          <h2 className="font-serif text-xl text-white">Paid plans</h2>
          <p className="mt-2">
            If a payment fails, is duplicated, or the Pro features do not activate after a
            successful payment, contact us within 7 days at [Contact email] with your order
            reference and we will fix it or refund the payment in full.
          </p>
        </section>
        <section>
          <h2 className="font-serif text-xl text-white">How refunds are made</h2>
          <p className="mt-2">
            Approved refunds go back to the original payment method through Razorpay and
            typically arrive within 5–7 business days, depending on your bank.
          </p>
        </section>
        <section>
          <h2 className="font-serif text-xl text-white">Contact</h2>
          <p className="mt-2">Refund requests and questions: [Contact email].</p>
        </section>
      </div>
    </main>
  );
}
