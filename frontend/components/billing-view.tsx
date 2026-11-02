"use client";

/**
 * In-app billing: current plan, trial, checkout.
 *
 * Checkout uses Razorpay Checkout.js, loaded on demand only when payments
 * are configured. Until keys are set, paid plans show "Payments coming
 * soon" instead of a dead button. The webhook (server-side) activates the
 * plan after a captured payment; this view polls /billing/me briefly after
 * a successful checkout so the new plan appears without a reload.
 */
import { useCallback, useEffect, useState } from "react";
import { billingApi, type BillingPlan } from "@/lib/api";
import { Badge, Button, Card, ErrorNote, PageHeader, Spinner } from "./ui";

type Me = {
  plan: string;
  effective_plan: string;
  trial_ends_at: string;
  trial_active: boolean;
  trial_used: boolean;
};

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open: () => void };
  }
}

function loadRazorpayScript(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Could not load the payment form."));
    document.body.appendChild(script);
  });
}

function priceLabel(plan: BillingPlan): string {
  if (plan.price_inr === 0) return "Free";
  if (plan.price_inr === null) return "Contact us";
  return `₹${plan.price_inr}/month`;
}

export function BillingView() {
  const [me, setMe] = useState<Me | null>(null);
  const [plans, setPlans] = useState<BillingPlan[] | null>(null);
  const [paymentsConfigured, setPaymentsConfigured] = useState(false);
  const [trialDays, setTrialDays] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError("");
    Promise.all([billingApi.me(), billingApi.plans()])
      .then(([meRes, plansRes]) => {
        setMe(meRes);
        setPlans(plansRes.plans);
        setPaymentsConfigured(plansRes.payments_configured);
        setTrialDays(plansRes.trial_days);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load billing."));
  }, []);

  useEffect(load, [load]);

  const startTrial = async () => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await billingApi.startTrial();
      setNotice("Trial started — you have Pro until the date shown below.");
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not start the trial.");
    } finally {
      setBusy(false);
    }
  };

  const pay = async (plan: BillingPlan) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const order = await billingApi.checkout(plan.id);
      await loadRazorpayScript();
      if (!window.Razorpay) throw new Error("Could not load the payment form.");
      const rzp = new window.Razorpay({
        key: order.key_id,
        amount: order.amount_paise,
        currency: order.currency,
        order_id: order.order_id,
        name: "Career Guidance AI",
        description: `${plan.name} plan`,
        handler: () => {
          setNotice("Payment received — activating your plan…");
          let attempts = 0;
          const poll = setInterval(() => {
            attempts += 1;
            billingApi
              .me()
              .then((next) => {
                setMe(next);
                if (next.effective_plan === plan.id || attempts >= 6) clearInterval(poll);
              })
              .catch(() => clearInterval(poll));
          }, 3000);
        },
      });
      rzp.open();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Checkout failed.");
    } finally {
      setBusy(false);
    }
  };

  if (error && !me) return <ErrorNote error={error} retry={load} />;
  if (!me || !plans) return <Spinner label="Loading billing…" />;

  const isCurrent = (id: string) => me.effective_plan === id;

  return (
    <div className="space-y-5">
      <PageHeader title="Billing" subtitle="Your plan, trial and payments." />

      {notice && (
        <Card className="border-ok/30">
          <p className="text-sm text-ok">{notice}</p>
        </Card>
      )}
      {error && <ErrorNote error={error} retry={load} />}

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm text-fg-2">Current plan</p>
            <p className="mt-1 font-serif text-2xl capitalize">{me.effective_plan}</p>
            {me.trial_active && (
              <p className="mt-1 text-sm text-accent">
                Trial active until {new Date(me.trial_ends_at).toLocaleDateString()}
              </p>
            )}
          </div>
          <div className="flex gap-2">
            {me.effective_plan === "free" && !me.trial_used && trialDays > 0 && (
              <Button onClick={startTrial} disabled={busy}>
                Start {trialDays}-day free trial
              </Button>
            )}
            {me.trial_used && !me.trial_active && me.effective_plan === "free" && (
              <Badge tone="muted">Trial used</Badge>
            )}
          </div>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        {plans.map((plan) => (
          <Card key={plan.id} className={plan.id === "pro" ? "border-accent/40" : undefined}>
            <div className="flex items-center justify-between">
              <h2 className="font-serif text-xl">{plan.name}</h2>
              {isCurrent(plan.id) && <Badge tone="ok">Current</Badge>}
            </div>
            <p className="mt-1 text-sm text-fg-2">{plan.tagline}</p>
            <p className="mt-3 text-2xl font-semibold">{priceLabel(plan)}</p>
            {plan.id === "pro" && trialDays > 0 && !me.trial_used && (
              <p className="mt-1 text-sm text-accent">Includes a {trialDays}-day free trial.</p>
            )}
            <ul className="mt-4 space-y-1.5">
              {plan.features.map((feature) => (
                <li key={feature} className="text-sm text-fg-2">· {feature}</li>
              ))}
            </ul>
            <div className="mt-5">
              {isCurrent(plan.id) ? (
                <Button variant="outline" disabled>
                  Current plan
                </Button>
              ) : plan.id === "free" ? (
                <p className="text-sm text-fg-2">Included in every plan.</p>
              ) : plan.id === "institute" ? (
                <p className="text-sm text-fg-2">Contact us — institutes are enrolled by an admin.</p>
              ) : paymentsConfigured ? (
                <Button onClick={() => pay(plan)} disabled={busy}>
                  Upgrade to {plan.name}
                </Button>
              ) : (
                <p className="text-sm text-fg-2">Payments coming soon — try the free trial meanwhile.</p>
              )}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
