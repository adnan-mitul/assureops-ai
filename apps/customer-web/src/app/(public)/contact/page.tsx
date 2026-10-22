"use client";

import { Button, Card, ErrorBanner, Field, Notice, PageHeader, inputClass } from "@assureops/ui/components";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { planById, planSummary, type Plan } from "@/lib/plans";

export default function ContactPage() {
  return <Suspense fallback={null}><ContactForm /></Suspense>;
}

function ContactForm() {
  const [form, setForm] = useState({ company: "", contact_email: "", message: "" });
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [error, setError] = useState<string | null>(null);
  const params = useSearchParams();  // the plan chosen on the landing page travels in the query string
  const chosen: Plan | undefined = planById(params.get("plan"));
  const plan = chosen ? { plan: chosen, yearly: params.get("billing") === "yearly" } : null;
  const planLine = plan && planSummary(plan.plan, plan.yearly);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setState("sending");
    setError(null);
    const res = await fetch("/public/inquiries", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...form, message: planLine ? `${planLine}

${form.message}` : form.message }) });
    if (res.ok) {
      setState("sent");
    } else {
      setState("idle");
      setError(res.status === 429 ? "Too many requests from this address; try again later." : "The inquiry could not be sent. Check the fields and try again.");
    }
  };

  return (
    <div className="mx-auto max-w-xl space-y-5">
      <PageHeader title="Contact AssureOps" subtitle="Tell us about the AI application you want assessed. We create your workspace and invite you by e-mail." />
      {state === "sent" ? (
        <Notice tone="success">Thank you. Your inquiry was received; you will get an invitation e-mail once your workspace is ready.</Notice>
      ) : (
        <Card className="p-6">
          {planLine && <div className="mb-4"><Notice tone="info">{planLine}. {plan?.plan.trialDays ? `Your ${plan.plan.trialDays}-day trial starts when you accept the workspace invitation.` : "We confirm the subscription with your workspace invitation."}</Notice></div>}
          <form className="grid gap-4" onSubmit={submit}>
            <Field label="Company"><input required minLength={2} maxLength={120} value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} className={inputClass} /></Field>
            <Field label="Work e-mail"><input required type="email" value={form.contact_email} onChange={(e) => setForm({ ...form, contact_email: e.target.value })} className={inputClass} /></Field>
            <Field label="What should we assess?" hint="At least 10 characters">
              <textarea required minLength={10} maxLength={4000} value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} className={`${inputClass} min-h-28`} />
            </Field>
            <div><Button type="submit" variant="primary" disabled={state === "sending"}>{state === "sending" ? "Sending…" : "Send inquiry"}</Button></div>
            {error && <ErrorBanner message={error} />}
          </form>
        </Card>
      )}
    </div>
  );
}
