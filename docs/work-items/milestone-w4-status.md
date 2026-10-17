# First working milestone (plan §45.1) — status

Journey: register release → run approval check → inspect evidence → review → change permission policy → old evidence stale → retest → publish a new scoped report, visible in both portals.

| Ticket | Scope | State |
|---|---|---|
| EX01 | Repository baseline, ADRs, adoption register | verified (this repo; REA/ECC pins still empty) |
| EX02 | Customer/staff identity, workspace model, RLS, case roles | verified (Keycloak OIDC, DB memberships, RLS tests) |
| EX03 | Images, CI gates, staging skeleton | proposed (`.github/workflows/ci.yml` written, not exercised; no images) |
| EX04 | Versioned release/control/coverage schemas, strict API contracts | verified for manifests and profile; generated client pending |
| EX05 | Durable jobs, outbox, attempts, fencing, cancellation | verified (fencing test; cancellation path implemented, race tests pending) |
| EX06 | Private artifacts, hashes, download authorization | in_progress (local content-addressed store; S3 pending) |
| EX07 | Synthetic refund MCP app, safe tool protocol, approval gateway | verified (real MCP 2026-07-28, approval binding tests) |
| EX08 | C03 vertical slice in both portals | verified in the browser: R1 → R2 → incident → R3 → review → publication |
| EX09 | REA sandbox and normalization | deferred_with_scope_disclosure |
| EX10 | C01–C10 checks and catalog | verified for 15 approved tests; C09 semantic results need reviewer confirmation |
| EX11 | Evidence graph, compatibility predicate, change/retest planner | verified (unit + journey) |
| EX12–EX15, EX17, EX19 | Model registry and qualified routes | deferred_with_scope_disclosure (all routes disabled) |
| EX16 | Runtime cohorts, events, incidents | verified (classification, gaps, reviewed closure) |
| EX18 | Assignments, evidence requests, independent review, publication | verified in the browser (assignment, separation of duties, semantic evidence review, incident closure, publication) |
| EX20–EX22 | GitHub App, production operations, benchmark | deferred_with_scope_disclosure |
