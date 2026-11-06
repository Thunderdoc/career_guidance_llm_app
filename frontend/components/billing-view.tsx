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
import { billingApi, type BillingPlan, type BillingSubscription } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Badge, Button, Card, ErrorNote, PageHeader, Spinner, inputCls } from "./ui";

type Me = {
  plan: string;
  effective_plan: string;
  trial_ends_at: string;
  trial_active: boolean;
  trial_used: boolean;
  subscription: BillingSubscription;
};

type Referral = { code: string; referrals: number; pending_rewards: number };

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
  const { t } = useI18n();
  const [me, setMe] = useState<Me | null>(null);
  const [plans, setPlans] = useState<BillingPlan[] | null>(null);
  const [paymentsConfigured, setPaymentsConfigured] = useState(false);
  const [subscriptionsEnabled, setSubscriptionsEnabled] = useState(false);
  const [trialDays, setTrialDays] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  // Phase 9: coupon + referral codes for checkout, and my referral summary.
  const [couponCode, setCouponCode] = useState("");
  const [referralCode, setReferralCode] = useState("");
  const [couponMsg, setCouponMsg] = useState("");
  const [couponOk, setCouponOk] = useState(false);
  const [referral, setReferral] = useState<Referral | null>(null);

  const load = useCallback(() => {
    setError("");
    Promise.all([billingApi.me(), billingApi.plans()])
      .then(([meRes, plansRes]) => {
        setMe(meRes);
        setPlans(plansRes.plans);
        setPaymentsConfigured(plansRes.payments_configured);
        setSubscriptionsEnabled(plansRes.subscriptions_enabled);
        setTrialDays(plansRes.trial_days);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load billing."));
    billingApi
      .myReferral()
      .then(setReferral)
      .catch(() => setReferral(null));
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

  const applyCoupon = async () => {
    if (!couponCode.trim()) return;
    setCouponMsg("");
    try {
      const res = await billingApi.validateCoupon(couponCode.trim(), "pro");
      if (res.valid) {
        setCouponOk(true);
        setCouponMsg(
          res.discount_preview_paise != null
            ? t("p9_coupon_valid", { amount: (res.discount_preview_paise / 100).toLocaleString() })
            : res.code || "",
        );
      } else {
        setCouponOk(false);
        setCouponMsg(res.reason || "");
      }
    } catch (e: unknown) {
      setCouponOk(false);
      setCouponMsg(e instanceof Error ? e.message : "");
    }
  };

  const pay = async (plan: BillingPlan) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const order = await billingApi.checkout(plan.id, couponCode.trim(), referralCode.trim());
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

  const subscribe = async (plan: BillingPlan) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const sub = await billingApi.subscribe(plan.id);
      await loadRazorpayScript();
      if (!window.Razorpay) throw new Error("Could not load the payment form.");
      const rzp = new window.Razorpay({
        key: sub.key_id,
        subscription_id: sub.subscription_id,
        name: "Career Guidance AI",
        description: `${plan.name} plan (subscription)`,
        handler: () => {
          setNotice("Subscription started — activating your plan…");
          load();
        },
      });
      rzp.open();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not start the subscription.");
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
            {me.subscription && (
              <p className="mt-1 text-sm text-fg-2">
                {t("p9_subscription_status", { status: me.subscription.status })}
                {me.subscription.current_period_end &&
                  ` · ${t("p9_subscription_until", {
                    date: new Date(me.subscription.current_period_end).toLocaleDateString(),
                  })}`}
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

      {paymentsConfigured && (
        <Card>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="text-sm text-fg-2" htmlFor="coupon-code">
                {t("p9_coupon_label")}
              </label>
              <div className="mt-1 flex gap-2">
                <input
                  id="coupon-code"
                  className={inputCls}
                  value={couponCode}
                  onChange={(e) => {
                    setCouponCode(e.target.value);
                    setCouponOk(false);
                    setCouponMsg("");
                  }}
                  placeholder={t("p9_coupon_placeholder")}
                />
                <Button variant="outline" onClick={applyCoupon} disabled={busy || !couponCode.trim()}>
                  {t("p9_coupon_apply")}
                </Button>
              </div>
              {couponMsg && (
                <p className={`mt-1 text-sm ${couponOk ? "text-ok" : "text-red-400"}`}>{couponMsg}</p>
              )}
            </div>
            <div>
              <label className="text-sm text-fg-2" htmlFor="referral-code">
                {t("p9_referral_label")}
              </label>
              <input
                id="referral-code"
                className={`${inputCls} mt-1`}
                value={referralCode}
                onChange={(e) => setReferralCode(e.target.value)}
                placeholder={t("p9_referral_placeholder")}
              />
            </div>
          </div>
        </Card>
      )}

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
                <div className="space-y-2">
                  <Button onClick={() => pay(plan)} disabled={busy}>
                    Upgrade to {plan.name}
                  </Button>
                  {subscriptionsEnabled && (
                    <>
                      <Button variant="outline" onClick={() => subscribe(plan)} disabled={busy}>
                        {t("p9_subscribe")}
                      </Button>
                      <p className="text-xs text-fg-2">{t("p9_subscribe_note")}</p>
                    </>
                  )}
                </div>
              ) : (
                <p className="text-sm text-fg-2">Payments coming soon — try the free trial meanwhile.</p>
              )}
            </div>
          </Card>
        ))}
      </div>

      {referral && (
        <Card>
          <h2 className="font-serif text-xl">{t("p9_my_referral_title")}</h2>
          <p className="mt-1 text-sm text-fg-2">{t("p9_my_referral_sub")}</p>
          <p className="mt-3 font-mono text-lg">{referral.code}</p>
          <p className="mt-1 text-sm text-fg-2">
            {t("p9_my_referral_count", { n: referral.referrals })} ·{" "}
            {t("p9_my_referral_pending", { n: referral.pending_rewards })}
          </p>
        </Card>
      )}
    </div>
  );
}
