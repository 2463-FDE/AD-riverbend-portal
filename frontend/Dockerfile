# Multi-stage: the build stage carries the full dev/test/lint toolchain to compile
# the Next bundle; the runtime stage installs production dependencies only, so Vitest,
# Vite, jsdom, Testing Library and ESLint never ship in the deployed image (codex r1).
# CI still runs the full install for typecheck/lint/test — that is a separate job and
# is unaffected by this split.

# ---- build stage ----
FROM node:22-slim AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .
# Internal gateway URL must be present at build time too: Next can constant-fold
# process.env into the standalone bundle, so an unset value bakes the localhost
# fallback. Compose still overrides this at runtime.
ENV GATEWAY_URL=http://gateway:8070
RUN npm run build

# ---- runtime stage ----
FROM node:22-slim AS runtime
WORKDIR /app

# Production dependencies only. `next start` (the CMD) serves the prebuilt `.next`
# bundle and needs next/react/react-dom at runtime, nothing from devDependencies.
COPY package.json package-lock.json* ./
RUN npm ci --omit=dev

COPY --from=build /app/.next ./.next
COPY --from=build /app/next.config.mjs ./next.config.mjs

# Same reason as the build stage: keep the baked default off localhost. Compose overrides.
ENV GATEWAY_URL=http://gateway:8070
EXPOSE 3070
CMD ["npm", "run", "start"]
