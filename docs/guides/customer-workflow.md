# Customer workflow: from "check my AI application" to a published report

This walks through one customer, Acme, assessing its own AI application end to end. Every step is a button in the customer portal (`http://localhost:3700` locally) or the staff portal (`http://localhost:3710`). Nothing about the application is predefined: no profile file and no seeded test plan.

Roles used below: **owner** (runs the workspace), **developer** (connects and changes one assigned application), **reviewer** (approves what someone else proposed), and on the AssureOps side an **analyst**, an independent **senior reviewer** and a **case manager**. One person never approves their own proposal.

## 0. What the application must offer

AssureOps tests the application from outside, over HTTP, as named test accounts. The application provides:

| Needed | Why |
|---|---|
| A reachable base URL (staging), or a private connector (relay) in your network if AssureOps cannot reach it | Every test request goes only to this origin; redirects are refused |
| `GET /health` | Connection check |
| `GET /manifest`: JSON with `application`, `release` and `components` (`id` → `type` and `fingerprint`) | Freezes exactly which release was assessed; a changed fingerprint shows what changed and what must be retested |
| Test accounts (one credential per actor, for example `customer`, `other_tenant`, `manager`) | Tests run as these actors. Credentials are encrypted and never shown again |
| The paths and methods tests may use (`allowed_paths`, `allowed_methods`) | The authorized scope; anything outside it is never sent |
| Optional: an events endpoint, or the event bridge | Runtime monitoring and incidents |

Synthetic accounts and data only: never real customers, real credentials or real money.

## 1. Get access

1. **Contact**: send the form at `/contact`; no account is needed. A case manager converts the inquiry into a workspace.
2. **Join**: the owner receives an invitation e-mail, signs up (or signs in) and accepts. The link works once, for that address only, for 7 days.
3. **Team**: under **Settings → Members**, invite a developer and a reviewer. Each gets an invitation e-mail.

(Locally, the demo users from `seed.py --users-only` can sign in directly; see the operator guide for the passwords and staff one-time codes.)

## 2. Register and connect the application

1. **Applications → Register application**: name, purpose (one or two sentences on what it does), environment and mode.
2. On **Connect**, the owner **assigns the developer** to it. The developer now gets this application's notices.
3. The developer fills the connection: adapter **HTTP/JSON**, base URL, manifest and health paths, authorized paths and methods, and one credential per actor.
4. **Verify connection**: AssureOps checks the destination policy, health, manifest, ownership, credentials and events, and lists any gaps. A gap is shown, never hidden.

## 3. Build the test plan (AI-built, no file)

On **Applications → AI**:

1. **Add a reference document** under *Approved reference sources*: your policy, requirements or design text (a reviewer approves it). The AI quotes from it.
2. **Run A** (requirement analysis). A reviewer, not the requester, **accepts** the requirements. Each must quote the document word for word, or it can only be rejected.
3. **Run C** (test proposal). It picks tests from the permitted catalogue for those requirements. A reviewer **accepts** it. Tests that could not run are removed and listed before review.
4. Under **Build the test plan**, enter the **declared facts** a model cannot know, for example `{"reply_path": "reply", "markers": ["INV-"], "expect_contains": ["14 days"]}`, and press **Build test plan**. It proposes one profile revision:
   - the accepted tests;
   - the release identity check;
   - the standard gate policy;
   - every untested control marked *not assessed*.
5. On **Connect**, a **different** owner or reviewer reviews and **activates** the plan. The person who built it cannot.

Alternatives: a **baseline** from a few declared facts on Connect, or a **JSON** profile written by an analyst. The team is notified at every step on the application's **Notice board**, under **Notifications**, and by e-mail or webhook.

## 4. Assess

1. **Releases → Submit release**: AssureOps collects the manifest and freezes the release identity. The team gets a change notice listing the changed components and how many tests to retest.
2. **Full assessment** the first time; later releases need only a retest. Each test runs in a disposable sandbox that can only reach your origin. Infrastructure errors show as *unverified*, never as passes or failures. An agent that never attempted the action under test shows as *inconclusive*.
3. Read the results per control on the **Overview**. Each result has:
   - a **result**: supported, failed, unverified or review required;
   - **evidence validity**: current or stale;
   - **evidence support %** and **coverage %**.

   AI-added tests need a reviewer to confirm their passing evidence.
4. **Findings**: every failure becomes a finding with its evidence. Fix it, submit the new release, and AssureOps retests only the tests the change affects. If the change cannot be mapped, it retests everything.

## 5. Get the report

1. **Cases → Submit a case**. The case manager assigns an analyst and an independent senior reviewer in the staff portal. Messages on the case notify the other side. Internal staff notes are never shown to or sent to the customer.
2. The analyst reviews the evidence, asks for anything missing (the customer answers on the case), and drafts the report from a frozen evidence snapshot. Phase F may draft the plain-language explanation; the analyst accepts or edits it. Numbers and verdicts always come from the snapshot.
3. The senior reviewer, not the analyst, **publishes** the exact snapshot.
4. The customer opens it under **Reports** and can download the **evidence bundle**: the report plus every cited piece of evidence, with SHA-256 hashes.

"Passing all the tests" means the gate is **ready**: no blocking failure, all evidence current, nothing unverified or awaiting review. The report states evidence support and coverage. It never says the application is safe, certified or compliant.

## 6. Stay current

- **Release gate in CI**: your pipeline asks AssureOps about an exact commit and gets a signed, expiring decision (`docs/integrations/customer-release-gate.yml`). A new incident invalidates it.
- **Monitoring**: the event bridge sends runtime events. Only a tool-side verified unauthorized effect opens an incident. Closing one is a reviewed decision.
- **Notice board**: every release, plan change, AI review and finished assessment is posted for the team automatically.
