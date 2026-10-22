// Subscription plans, priced in Bangladeshi taka (BDT). One source for the landing page and the contact form.
// Prices exclude VAT. Change them here only.

export type Plan = {
  id: "trial" | "starter" | "growth" | "enterprise";
  name: string;
  monthly: number | null; // null: priced per agreement; 0: free
  blurb: string;
  features: string[];
  highlight?: boolean;
  trialDays?: number;
};

export const TRIAL_DAYS = 14;

export const PLANS: Plan[] = [
  {
    id: "trial", name: "Free trial", monthly: 0, trialDays: TRIAL_DAYS, blurb: `Try AssureOps on one application for ${TRIAL_DAYS} days. No payment.`,
    features: ["1 application", "1 full assessment", "Published report with evidence", "Notice board and e-mail updates", "Upgrade any time, keep your results"],
  },
  {
    id: "starter", name: "Starter", monthly: 4999, blurb: "One AI application, tested before every release.",
    features: ["1 application", "2 full assessments a month", "Retests of changed parts", "Published report with evidence bundle", "E-mail support"],
  },
  {
    id: "growth", name: "Growth", monthly: 14999, highlight: true, blurb: "For teams shipping several AI features.",
    features: ["Up to 5 applications", "Unlimited assessments and retests", "AI-built test plans", "GitHub release gate on every commit",
               "Runtime monitoring and incidents", "Priority support"],
  },
  {
    id: "enterprise", name: "Enterprise", monthly: null, blurb: "Private networks, dedicated reviewers, agreed response times.",
    features: ["Unlimited applications", "Private connector inside your network", "Dedicated AssureOps reviewer", "Service levels and onboarding",
               "Custom controls and reports"],
  },
];

export const YEARLY_MONTHS_CHARGED = 10; // yearly billing: 12 months for the price of 10

export function taka(amount: number): string {
  return `৳${amount.toLocaleString("en-IN")}`; // lakh grouping, as prices are written in Bangladesh
}

export function planById(id: string | null | undefined): Plan | undefined {
  return PLANS.find((p) => p.id === id);
}

/** One line describing a chosen plan, for the contact form and the inquiry. */
export function planSummary(plan: Plan, yearly: boolean): string {
  if (plan.trialDays) return `Plan: ${plan.name} (${plan.trialDays} days, free)`;
  if (plan.monthly === null) return `Plan: ${plan.name} (custom pricing)`;
  return `Plan: ${plan.name} (${yearly ? `${taka(plan.monthly * YEARLY_MONTHS_CHARGED)} / year` : `${taka(plan.monthly)} / month`})`;
}
