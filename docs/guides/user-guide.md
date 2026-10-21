# AssureOps user guide

AssureOps assesses an AI application against reviewed requirements, keeps the evidence and tells you when that evidence goes stale. Its reports describe tested readiness within a stated scope. They are not a certification or a permission to launch.

There are two portals. Customers use the **customer portal**; AssureOps staff use the **staff portal**. Both portals sign you in through the identity provider (Keycloak). Staff sign-in always asks for a password and a one-time code.

## Customer roles

| Role | Can do |
|---|---|
| Owner | Everything below, plus: register applications, invite members, change roles, assign developers to applications, issue relay credentials, set the data policy |
| Developer | Change only the applications an owner assigned to them: connect, propose a profile, submit releases, run assessments, open cases, request risk acceptance |
| Reviewer | Approve: activate profiles (when someone else proposed them), accept or reject AI proposals, approve risk acceptances |
| Viewer | Read only |

A person who proposes something (a profile, a risk acceptance, an AI request) never approves it.

## From first contact to a published report

1. **Contact**: send the form at `/contact` in the customer portal. No account is needed.
2. **Join**: AssureOps creates your workspace and e-mails the owner an invitation. Open the link, create your account at the sign-in page if you have none, and accept. The invitation works once, only for the address it was sent to, and expires after 7 days.
3. **Team**: under **Settings → Members**, invite developers, reviewers and viewers. Role changes ask for confirmation and take effect on that person's next request.
4. **Register and assign**: register the application, then assign one or more developers on **Applications → Connect**.
5. **Connect**: the developer chooses an adapter (HTTP/JSON for most applications) and enters the base URL, scope and test credentials. Credentials are encrypted and never shown again. If AssureOps cannot reach the target, use the **private connector (relay)**: it runs in your network and connects outbound only.
6. **Verify**: AssureOps checks the destination, health, manifest, ownership and credentials, and lists any gaps.
7. **Profile**: a profile lists the controls to assess and the tests that cover them. One person proposes it; another activates it. Controls without tests stay visible as *not assessed* or, with a reviewed reason, *not applicable*.
8. **Release**: submit the running release. AssureOps collects its manifest and freezes its identity.
9. **Assess**: run a full assessment. Each test runs in a disposable sandbox that can reach only your application's origin. Results appear per control, together with how current the evidence is.
10. **Findings and fixes**: failures become findings with their evidence. Fix, submit the new release, and AssureOps retests only what the change affects, unless the change cannot be mapped, in which case it retests everything.
11. **Case and report**: open an assessment case. An AssureOps analyst prepares the report and a different, independent reviewer publishes the exact snapshot. You read it under **Reports** and can download an evidence bundle: the report plus cited evidence, with SHA-256 hashes.
12. **Release gate**: your CI asks AssureOps about an exact commit and receives a signed, expiring decision. Pull requests are judged on their merge candidate.
13. **Monitoring**: the event bridge sends runtime events. Only a tool-side verified unauthorized effect opens an incident; closing one is a reviewed decision.

## Reading the results

- **Evidence support / coverage** are percentages of *assessed evidence*. They are not a safety score.
- **Gate** is `ready`, `incomplete` or `blocked`. Critical and high failures block. Stale, unverified or unreviewed evidence makes the gate incomplete.
- **Risk acceptance** (owners, developers and reviewers) is release-bound, expires within 90 days and needs a second person to approve it. It never covers a critical failure or a verified runtime violation. It changes the gate only if your reviewed profile allows that severity. The failure itself stays visible.
- **AI proposals** (requirements, dependency links, tests, explanations) are suggestions. Someone other than the requester accepts or rejects them, and acceptance only creates further proposals.

## Notifications

The bell shows notifications addressed to you: invitations, assignments and role changes. A notification never grants access by itself.
