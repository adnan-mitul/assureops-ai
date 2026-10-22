// Subscription plans, priced in Bangladeshi taka (BDT). One source for the landing page and the contact form.
// Prices exclude VAT. Change them here only.

export type Plan = {
  id: "starter" | "growth" | "enterprise";
  name: string;
  monthly: number | null; // null: priced per agreement
  blurb: string;
  features: string[];
  highlight?: boolean;
};

export const PLANS: Plan[] = [
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
