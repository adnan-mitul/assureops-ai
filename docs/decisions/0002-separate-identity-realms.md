# 0002 — Separate identity realms for customers and staff

Status: accepted.

## Context
Plan §35.1 requires a staff ingress with its own client, identity and access policy. During the browser journey both portals shared one Keycloak realm: signing in to the staff portal replaced the browser's single sign-on session, and the customer portal then received a staff identity (correctly refused by the API, but confusing). Both portals also shared cookie names on `localhost`.

## Decision
- Customers authenticate in realm `assureops` (client `customer-web`, audience `assureops-customer-api`); staff in realm `assureops-staff` (client `staff-web`, audience `assureops-staff-api`, shorter idle timeout, fresh login on every sign-in).
- The API pins each surface to its own issuer and audience.
- Session, CSRF and login cookies are named per portal.
- A signed-in identity without a role in a portal sees a "No access" page with sign-out, never an endless loading state.

## Consequences
Customer and staff sessions can coexist in one browser. Staff MFA can be enforced on the staff realm alone before production.
