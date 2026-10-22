"use client";

import { ArrowRight, BadgeCheck, Check, FileCheck2, GitBranch, LogIn, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PLANS, YEARLY_MONTHS_CHARGED, taka } from "@/lib/plans";

const STEPS = [
  { icon: GitBranch, title: "Submit your application", body: "Give the GitHub link, the live URL and the environment to test. Test accounts are stored encrypted." },
  { icon: Users, title: "An AssureOps developer tests it", body: "A dedicated developer verifies the connection, builds the test plan and runs every test in an isolated sandbox." },
  { icon: BadgeCheck, title: "An independent admin approves", body: "A second person reviews the plan and the evidence. Nobody approves their own work." },
  { icon: FileCheck2, title: "You receive the report", body: "Evidence-backed results per control, with a downloadable evidence bundle and a release gate for your pipeline." },
];

export default function LandingPage() {
  const [yearly, setYearly] = useState(false);

  return (
    <div className="w-full bg-canvas text-ink">
      <header className="sticky top-0 z-10 border-b border-line bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-8">
          <Link href="/" className="flex items-center gap-2 font-bold text-brand-700">
            <span className="grid size-9 place-items-center rounded-lg bg-brand-50"><ShieldCheck className="size-5" aria-hidden /></span>
            AssureOps AI
          </Link>
          <nav className="flex items-center gap-1 text-sm sm:gap-4">
            <a href="#how" className="hidden rounded-md px-2 py-1 hover:bg-brand-50 sm:inline">How it works</a>
            <a href="#pricing" className="rounded-md px-2 py-1 hover:bg-brand-50">Pricing</a>
            <Link href="/auth/login?returnTo=/overview" className="inline-flex items-center gap-1.5 rounded-lg bg-brand-700 px-3.5 py-2 font-medium text-white hover:bg-brand-800">
              <LogIn className="size-4" aria-hidden /> Sign in
            </Link>
          </nav>
        </div>
      </header>

      <section className="mx-auto max-w-6xl px-4 pt-16 pb-12 sm:px-8 sm:pt-24">
        <p className="inline-flex items-center gap-2 rounded-full bg-brand-100 px-3 py-1 text-xs font-semibold text-brand-800">
          <ShieldCheck className="size-3.5" aria-hidden /> Release assurance for AI applications
        </p>
        <h1 className="mt-5 max-w-3xl text-4xl font-bold tracking-tight sm:text-5xl">
          Know your AI application is ready <span className="text-brand-700">before</span> every release.
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-muted">
          AssureOps tests what your AI agent actually does: who it serves, which data it shows, which actions it takes. Every result
          is backed by evidence and approved by a second person. Never &ldquo;certified&rdquo;, always proven.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/contact?plan=growth" className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-5 py-3 font-semibold text-white hover:bg-brand-800">
            Get started <ArrowRight className="size-4" aria-hidden />
          </Link>
          <a href="#pricing" className="inline-flex items-center gap-2 rounded-lg border border-line bg-white px-5 py-3 font-semibold hover:bg-brand-50">
            See pricing
          </a>
        </div>
      </section>

      <section id="how" className="border-y border-line bg-white">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-8">
          <h2 className="text-2xl font-bold tracking-tight">How it works</h2>
          <ol className="mt-8 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <li key={s.title} className="rounded-xl border border-line bg-canvas p-5">
                <span className="grid size-10 place-items-center rounded-lg bg-brand-700 text-white"><s.icon className="size-5" aria-hidden /></span>
                <p className="mt-4 text-xs font-semibold text-brand-700">Step {i + 1}</p>
                <h3 className="mt-1 font-semibold">{s.title}</h3>
                <p className="mt-2 text-sm text-muted">{s.body}</p>
              </li>))}
          </ol>
        </div>
      </section>

      <section id="pricing" className="mx-auto max-w-6xl px-4 py-16 sm:px-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Subscription plans</h2>
            <p className="mt-1 text-sm text-muted">Prices in Bangladeshi taka (BDT), excluding VAT. Cancel any time.</p>
          </div>
          <div role="group" aria-label="Billing period" className="inline-flex rounded-lg border border-line bg-white p-1 text-sm">
            {[["Monthly", false], ["Yearly (2 months free)", true]].map(([label, value]) => (
              <button key={String(label)} type="button" aria-pressed={yearly === value} onClick={() => setYearly(value as boolean)}
                className={`rounded-md px-3 py-1.5 font-medium ${yearly === value ? "bg-brand-700 text-white" : "hover:bg-brand-50"}`}>{label}</button>))}
          </div>
        </div>
        <div className="mt-8 grid gap-5 lg:grid-cols-3">
          {PLANS.map((p) => (
            <div key={p.id} className={`flex flex-col rounded-2xl border bg-white p-6 ${p.highlight ? "border-brand-600 shadow-lg ring-1 ring-brand-600" : "border-line"}`}>
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold">{p.name}</h3>
                {p.highlight && <span className="rounded-full bg-brand-100 px-2.5 py-0.5 text-xs font-semibold text-brand-800">Most popular</span>}
              </div>
              <p className="mt-1 text-sm text-muted">{p.blurb}</p>
              <p className="mt-5">
                {p.monthly === null ? <span className="text-3xl font-bold">Custom</span> : yearly ? (
                  <><span className="text-3xl font-bold">{taka(p.monthly * YEARLY_MONTHS_CHARGED)}</span><span className="text-sm text-muted"> / year</span></>
                ) : (
                  <><span className="text-3xl font-bold">{taka(p.monthly)}</span><span className="text-sm text-muted"> / month</span></>
                )}
              </p>
              <ul className="mt-5 flex-1 space-y-2 text-sm">
                {p.features.map((f) => <li key={f} className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-brand-600" aria-hidden />{f}</li>)}
              </ul>
              <Link href={`/contact?plan=${p.id}${yearly ? "&billing=yearly" : ""}`}
                className={`mt-6 inline-flex justify-center rounded-lg px-4 py-2.5 font-semibold ${p.highlight ? "bg-brand-700 text-white hover:bg-brand-800" : "border border-line hover:bg-brand-50"}`}>
                {p.monthly === null ? "Talk to us" : `Choose ${p.name}`}
              </Link>
            </div>))}
        </div>
      </section>

      <footer className="border-t border-line bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-6 text-sm text-muted sm:px-8">
          <span className="flex items-center gap-2"><ShieldCheck className="size-4 text-brand-700" aria-hidden /> AssureOps AI. Evidence-backed readiness, not a certification.</span>
          <span className="flex gap-4"><Link href="/contact" className="hover:text-ink">Contact</Link><Link href="/auth/login?returnTo=/overview" className="hover:text-ink">Sign in</Link></span>
        </div>
      </footer>
    </div>
  );
}
