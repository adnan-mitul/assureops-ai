"use client";

import {
  ArrowRight, BadgeCheck, Bell, Bot, Building2, Check, ChevronDown, CircleCheck, Clock3, FileCheck2, GitBranch, Landmark, Lock, LogIn,
  RefreshCw, ShieldCheck, ShoppingCart, Sparkles, TriangleAlert, Users, XCircle,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { PLANS, TRIAL_DAYS, YEARLY_MONTHS_CHARGED, taka } from "@/lib/plans";

const SIGN_IN = "/auth/login?returnTo=/overview";
const TRIAL = "/contact?plan=trial";

const PROBLEMS = [
  { icon: TriangleAlert, title: "AI agents take real actions", body: "They issue refunds, read customer records and call tools. One wrong answer can cost money or leak data." },
  { icon: RefreshCw, title: "Every change can break what worked", body: "A new prompt, model or tool quietly changes behaviour. Yesterday's test result no longer tells the truth." },
  { icon: Clock3, title: "Manual reviews are slow", body: "Teams re-check everything by hand for every release, or skip it. Neither scales." },
];

const CONTROLS = [
  ["Access control", "Only the right people can do privileged things."],
  ["Customer isolation", "One customer never sees another customer's data."],
  ["Approvals", "Big actions (like large refunds) need a valid approval first."],
  ["Tool safety", "The agent only uses tools and websites it is allowed to."],
  ["Prompt injection", "Hidden instructions in documents cannot take control."],
  ["Data privacy", "Secrets and private values never leak in answers."],
  ["Run limits", "The agent stops at its step, time and cost budgets."],
  ["No double actions", "A retried request never pays or refunds twice."],
  ["Grounded answers", "Answers cite real sources, or say “I don't know”."],
  ["Release identity", "We prove the tested version is the one running."],
];

const STEPS = [
  { icon: GitBranch, title: "Submit your application", body: "Give its GitHub link, the URL where it runs and the environment (staging or production). Takes 2 minutes." },
  { icon: Users, title: "An AssureOps developer tests it", body: "We connect safely, build a test plan for your application and run every test in an isolated sandbox." },
  { icon: BadgeCheck, title: "An independent admin approves", body: "A second person checks the plan and the evidence. Nobody approves their own work." },
  { icon: FileCheck2, title: "You get the report", body: "Clear results per area, the evidence behind each one, and what to fix. You are notified by e-mail." },
];

const FEATURES = [
  { icon: FileCheck2, title: "Evidence-backed report", body: "Every result links to the recorded request and response, downloadable with tamper-evident hashes." },
  { icon: RefreshCw, title: "Retest only what changed", body: "New release? We compare it with the last one and re-run only the affected tests, about 40% fewer runs." },
  { icon: GitBranch, title: "GitHub release gate", body: "Your pipeline asks us before deploying a commit. Untested or failing commits don't ship." },
  { icon: Bot, title: "AI-assisted test plans", body: "AI proposes requirements and tests from your documents. People approve them; AI never decides a result." },
  { icon: Bell, title: "Notice board and e-mail", body: "Your team hears about every release, test run and report automatically." },
  { icon: Lock, title: "Private by design", body: "Test accounts are encrypted, tests use synthetic data, and each customer's data is isolated." },
];

const AUDIENCE = [
  { icon: Sparkles, title: "AI startups", body: "Show customers and investors that your agent is tested, release by release." },
  { icon: Landmark, title: "Banks and fintech", body: "Prove approvals, limits and data isolation before an AI assistant touches money." },
  { icon: ShoppingCart, title: "E-commerce and support", body: "Make sure refund and order bots follow your policy and never leak other customers' data." },
  { icon: Building2, title: "Enterprises and government", body: "Independent, reviewed evidence for every AI release, with a private connector for internal systems." },
];

const FAQ = [
  ["What does the free trial include?", `${TRIAL_DAYS} days, one application, one full assessment and the published report. No payment details are needed. Upgrade any time and keep your results.`],
  ["Do you need our source code?", "No. We test your running application over HTTPS, like a real user would. The GitHub link lets us tie each result to an exact commit and, if you want, block untested commits from deploying."],
  ["Is our data safe?", "Tests use synthetic test accounts, never real customers. Credentials are stored encrypted, every customer's data is isolated, and we never train models on your evidence."],
  ["Does AI decide whether we pass?", "No. AI only proposes requirements and tests. Results come from fixed rules and recorded evidence, and a second person approves the report."],
  ["What does the report say?", "For each area: supported, failed, unverified or needs review, with how current the evidence is and links to it. It never claims the application is “safe” or “certified”, only what was proven."],
  ["How do we pay?", "Plans are billed in taka, monthly or yearly (two months free). Prices exclude VAT. Enterprise is invoiced by agreement."],
];

function ResultPreview() {
  const rows: [string, "pass" | "fail" | "review"][] = [["Access control", "pass"], ["Customer isolation", "pass"], ["Approvals", "fail"],
    ["Prompt injection", "pass"], ["Grounded answers", "review"]];
  return (
    <div className="rounded-2xl border border-line bg-white p-5 shadow-xl shadow-brand-800/10">
      <div className="flex items-center justify-between">
        <div><p className="text-xs text-muted">Refund Bot · release 2.4.1 · staging</p><p className="font-semibold">Assessment result</p></div>
        <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-700">Gate: blocked</span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 text-center">
        <div className="rounded-lg bg-canvas p-3"><p className="text-2xl font-bold text-brand-700">80%</p><p className="text-xs text-muted">evidence support</p></div>
        <div className="rounded-lg bg-canvas p-3"><p className="text-2xl font-bold text-brand-700">100%</p><p className="text-xs text-muted">coverage</p></div>
      </div>
      <ul className="mt-4 space-y-2 text-sm">
        {rows.map(([name, state]) => (
          <li key={name} className="flex items-center justify-between rounded-lg border border-line px-3 py-2">
            <span>{name}</span>
            {state === "pass" ? <span className="flex items-center gap-1 text-xs font-medium text-emerald-700"><CircleCheck className="size-4" aria-hidden />Supported</span>
              : state === "fail" ? <span className="flex items-center gap-1 text-xs font-medium text-red-700"><XCircle className="size-4" aria-hidden />Failed</span>
                : <span className="flex items-center gap-1 text-xs font-medium text-amber-700"><Clock3 className="size-4" aria-hidden />Review</span>}
          </li>))}
      </ul>
      <p className="mt-3 text-xs text-muted">Example. &ldquo;Approvals failed: a 25,000 refund went through without a manager&apos;s approval.&rdquo; Fix it, submit again, and only the affected tests re-run.</p>
    </div>
  );
}

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
          <nav className="flex items-center gap-1 text-sm sm:gap-3">
            <a href="#how" className="hidden rounded-md px-2 py-1 hover:bg-brand-50 md:inline">How it works</a>
            <a href="#tests" className="hidden rounded-md px-2 py-1 hover:bg-brand-50 md:inline">What we test</a>
            <a href="#pricing" className="rounded-md px-2 py-1 hover:bg-brand-50">Pricing</a>
            <a href="#faq" className="hidden rounded-md px-2 py-1 hover:bg-brand-50 sm:inline">FAQ</a>
            <Link href={SIGN_IN} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-2 font-medium hover:bg-brand-50">
              <LogIn className="size-4" aria-hidden /> Sign in
            </Link>
            <Link href={TRIAL} className="hidden rounded-lg bg-brand-700 px-3.5 py-2 font-medium text-white hover:bg-brand-800 sm:inline-flex">Free trial</Link>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto grid max-w-6xl items-center gap-10 px-4 pt-14 pb-14 sm:px-8 lg:grid-cols-[1.15fr_1fr] lg:pt-20">
        <div>
          <p className="inline-flex items-center gap-2 rounded-full bg-brand-100 px-3 py-1 text-xs font-semibold text-brand-800">
            <ShieldCheck className="size-3.5" aria-hidden /> Testing and release assurance for AI agents
          </p>
          <h1 className="mt-5 text-4xl font-bold tracking-tight sm:text-5xl">
            Know your AI application is ready <span className="text-brand-700">before</span> every release.
          </h1>
          <p className="mt-5 text-lg text-muted">
            We test what your AI agent actually <em>does</em>: who it serves, what data it shows and which actions it takes.
            You get a clear report with proof for every result, checked by a second person.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Link href={TRIAL} className="inline-flex items-center gap-2 rounded-lg bg-brand-700 px-5 py-3 font-semibold text-white hover:bg-brand-800">
              Start {TRIAL_DAYS}-day free trial <ArrowRight className="size-4" aria-hidden />
            </Link>
            <a href="#how" className="inline-flex items-center gap-2 rounded-lg border border-line bg-white px-5 py-3 font-semibold hover:bg-brand-50">See how it works</a>
          </div>
          <ul className="mt-6 flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted">
            {[`${TRIAL_DAYS} days free, no payment`, "Synthetic test data only", "Every result reviewed by a person"].map((t) => (
              <li key={t} className="flex items-center gap-1.5"><Check className="size-4 text-brand-600" aria-hidden />{t}</li>))}
          </ul>
        </div>
        <ResultPreview />
      </section>

      {/* Problem */}
      <section className="border-y border-line bg-white">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-8">
          <p className="text-sm font-semibold text-brand-700">Why it matters</p>
          <h2 className="mt-1 text-3xl font-bold tracking-tight">Normal testing doesn&apos;t cover what AI agents can do</h2>
          <div className="mt-8 grid gap-5 md:grid-cols-3">
            {PROBLEMS.map((p) => (
              <div key={p.title} className="rounded-xl border border-line bg-canvas p-5">
                <p.icon className="size-6 text-brand-700" aria-hidden />
                <h3 className="mt-3 font-semibold">{p.title}</h3>
                <p className="mt-2 text-sm text-muted">{p.body}</p>
              </div>))}
          </div>
        </div>
      </section>

      {/* What we test */}
      <section id="tests" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-16 sm:px-8">
        <p className="text-sm font-semibold text-brand-700">What we test</p>
        <h2 className="mt-1 text-3xl font-bold tracking-tight">10 areas, in plain language</h2>
        <p className="mt-2 max-w-2xl text-muted">Every application is tested against the areas that apply to it. Areas we did not test stay visible as &ldquo;not assessed&rdquo;, never hidden.</p>
        <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {CONTROLS.map(([name, body], i) => (
            <div key={name} className="rounded-xl border border-line bg-white p-4">
              <p className="text-xs font-semibold text-brand-700">{String(i + 1).padStart(2, "0")}</p>
              <h3 className="mt-1 text-sm font-semibold">{name}</h3>
              <p className="mt-1 text-xs text-muted">{body}</p>
            </div>))}
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="scroll-mt-20 border-y border-line bg-white">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-8">
          <p className="text-sm font-semibold text-brand-700">How it works</p>
          <h2 className="mt-1 text-3xl font-bold tracking-tight">Four simple steps</h2>
          <ol className="mt-8 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <li key={s.title} className="relative rounded-xl border border-line bg-canvas p-5">
                <span className="grid size-10 place-items-center rounded-lg bg-brand-700 text-white"><s.icon className="size-5" aria-hidden /></span>
                <p className="mt-4 text-xs font-semibold text-brand-700">Step {i + 1}</p>
                <h3 className="mt-1 font-semibold">{s.title}</h3>
                <p className="mt-2 text-sm text-muted">{s.body}</p>
              </li>))}
          </ol>
          <p className="mt-6 text-sm text-muted">Typical first result: within 2–3 working days. Later releases are faster, because only what changed is tested again.</p>
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-6xl px-4 py-16 sm:px-8">
        <p className="text-sm font-semibold text-brand-700">What you get</p>
        <h2 className="mt-1 text-3xl font-bold tracking-tight">Everything to release AI with confidence</h2>
        <div className="mt-8 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="flex gap-4 rounded-xl border border-line bg-white p-5">
              <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-700"><f.icon className="size-5" aria-hidden /></span>
              <div><h3 className="font-semibold">{f.title}</h3><p className="mt-1 text-sm text-muted">{f.body}</p></div>
            </div>))}
        </div>
      </section>

      {/* Audience */}
      <section className="border-y border-line bg-white">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-8">
          <p className="text-sm font-semibold text-brand-700">Who it&apos;s for</p>
          <h2 className="mt-1 text-3xl font-bold tracking-tight">Built for teams whose AI takes real actions</h2>
          <div className="mt-8 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
            {AUDIENCE.map((a) => (
              <div key={a.title} className="rounded-xl border border-line bg-canvas p-5">
                <a.icon className="size-6 text-brand-700" aria-hidden />
                <h3 className="mt-3 font-semibold">{a.title}</h3>
                <p className="mt-2 text-sm text-muted">{a.body}</p>
              </div>))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="mx-auto max-w-6xl scroll-mt-20 px-4 py-16 sm:px-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-semibold text-brand-700">Pricing</p>
            <h2 className="mt-1 text-3xl font-bold tracking-tight">Start free, then pick a plan</h2>
            <p className="mt-1 text-sm text-muted">Prices in Bangladeshi taka (BDT), excluding VAT. Cancel any time.</p>
          </div>
          <div role="group" aria-label="Billing period" className="inline-flex rounded-lg border border-line bg-white p-1 text-sm">
            {[["Monthly", false], ["Yearly (2 months free)", true]].map(([label, value]) => (
              <button key={String(label)} type="button" aria-pressed={yearly === value} onClick={() => setYearly(value as boolean)}
                className={`rounded-md px-3 py-1.5 font-medium ${yearly === value ? "bg-brand-700 text-white" : "hover:bg-brand-50"}`}>{label}</button>))}
          </div>
        </div>
        <div className="mt-8 grid gap-5 md:grid-cols-2 lg:grid-cols-4">
          {PLANS.map((p) => (
            <div key={p.id} className={`flex flex-col rounded-2xl border bg-white p-6 ${p.highlight ? "border-brand-600 shadow-lg ring-1 ring-brand-600" : "border-line"}`}>
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-lg font-semibold">{p.name}</h3>
                {p.highlight && <span className="rounded-full bg-brand-100 px-2.5 py-0.5 text-xs font-semibold text-brand-800">Most popular</span>}
                {p.trialDays && <span className="rounded-full bg-sky-50 px-2.5 py-0.5 text-xs font-semibold text-sky-700">{p.trialDays} days</span>}
              </div>
              <p className="mt-1 text-sm text-muted">{p.blurb}</p>
              <p className="mt-5">
                {p.monthly === null ? <span className="text-3xl font-bold">Custom</span>
                  : p.monthly === 0 ? <><span className="text-3xl font-bold">৳0</span><span className="text-sm text-muted"> for {p.trialDays} days</span></>
                    : yearly ? <><span className="text-3xl font-bold">{taka(p.monthly * YEARLY_MONTHS_CHARGED)}</span><span className="text-sm text-muted"> / year</span></>
                      : <><span className="text-3xl font-bold">{taka(p.monthly)}</span><span className="text-sm text-muted"> / month</span></>}
              </p>
              <ul className="mt-5 flex-1 space-y-2 text-sm">
                {p.features.map((f) => <li key={f} className="flex gap-2"><Check className="mt-0.5 size-4 shrink-0 text-brand-600" aria-hidden />{f}</li>)}
              </ul>
              <Link href={`/contact?plan=${p.id}${yearly && p.monthly ? "&billing=yearly" : ""}`}
                className={`mt-6 inline-flex justify-center rounded-lg px-4 py-2.5 font-semibold ${p.highlight || p.trialDays ? "bg-brand-700 text-white hover:bg-brand-800" : "border border-line hover:bg-brand-50"}`}>
                {p.trialDays ? "Start free trial" : p.monthly === null ? "Talk to us" : `Choose ${p.name}`}
              </Link>
            </div>))}
        </div>
      </section>

      {/* FAQ */}
      <section id="faq" className="scroll-mt-20 border-t border-line bg-white">
        <div className="mx-auto max-w-3xl px-4 py-16 sm:px-8">
          <p className="text-sm font-semibold text-brand-700">FAQ</p>
          <h2 className="mt-1 text-3xl font-bold tracking-tight">Common questions</h2>
          <div className="mt-8 divide-y divide-line rounded-xl border border-line">
            {FAQ.map(([q, a]) => (
              <details key={q} className="group px-5 py-4">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                  {q}<ChevronDown className="size-4 shrink-0 text-muted transition group-open:rotate-180" aria-hidden />
                </summary>
                <p className="mt-2 text-sm text-muted">{a}</p>
              </details>))}
          </div>
        </div>
      </section>

      {/* Final call to action */}
      <section className="bg-brand-800 text-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-6 px-4 py-14 sm:px-8">
          <div>
            <h2 className="text-2xl font-bold sm:text-3xl">Test your AI application free for {TRIAL_DAYS} days</h2>
            <p className="mt-2 text-brand-100">Submit one application, get a reviewed report. No payment details needed.</p>
          </div>
          <Link href={TRIAL} className="inline-flex items-center gap-2 rounded-lg bg-white px-5 py-3 font-semibold text-brand-800 hover:bg-brand-50">
            Start free trial <ArrowRight className="size-4" aria-hidden />
          </Link>
        </div>
      </section>

      <footer className="border-t border-line bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-6 text-sm text-muted sm:px-8">
          <span className="flex items-center gap-2"><ShieldCheck className="size-4 text-brand-700" aria-hidden /> AssureOps AI. Evidence-backed readiness, not a certification.</span>
          <span className="flex gap-4"><a href="#pricing" className="hover:text-ink">Pricing</a><Link href="/contact" className="hover:text-ink">Contact</Link><Link href={SIGN_IN} className="hover:text-ink">Sign in</Link></span>
        </div>
      </footer>
    </div>
  );
}
