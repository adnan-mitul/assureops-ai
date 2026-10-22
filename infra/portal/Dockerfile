# Customer or staff portal (Next.js standalone server). Build once per portal:
#   docker build -f infra/portal/Dockerfile --build-arg APP=customer-web --build-arg PORTAL_ID=customer-web -t assureops-customer-web .
# Server-side settings (OIDC client secret, session key, API URL) come from the environment at run time.
FROM node:22.11.0-bookworm-slim AS build
ARG APP
ARG PORTAL_ID
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/customer-web/package.json apps/customer-web/package.json
COPY apps/staff-web/package.json apps/staff-web/package.json
COPY packages/ui/package.json packages/ui/package.json
RUN npm ci --ignore-scripts
COPY packages/ui packages/ui
COPY apps/${APP} apps/${APP}
ENV NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_PORTAL_ID=${PORTAL_ID} NEXT_STANDALONE=1
RUN npm --workspace apps/${APP} run build && mkdir -p apps/${APP}/public

FROM node:22.11.0-bookworm-slim
ARG APP
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0
WORKDIR /srv
COPY --from=build /repo/apps/${APP}/.next/standalone ./
COPY --from=build /repo/apps/${APP}/.next/static ./apps/${APP}/.next/static
COPY --from=build /repo/apps/${APP}/public ./apps/${APP}/public
RUN ln -s /srv/apps/${APP}/server.js /srv/server.js
USER node
CMD ["node", "/srv/server.js"]
