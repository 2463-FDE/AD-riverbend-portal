# Multi-stage on purpose (frontend-rebuild decision #11). The existing
# frontend/Dockerfile is a single stage running a bare `npm install`, so it ships
# devDependencies into the image it runs; copying that shape here would put a
# browser driver and a test runner in a runtime image. Neither Vitest nor the
# Chromium binary may reach the stage below.
FROM node:22-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# No build-time GATEWAY_URL or ORIGIN, and that is the point: SvelteKit reads
# both at request time (ADR 0012 §4, ADR 0015 §3) via $env/dynamic/private, so
# nothing about the deployment is baked into the artifact. The Next.js image
# next door has to bake GATEWAY_URL because Next constant-folds it.
RUN npm run build

FROM node:22-slim AS runtime

WORKDIR /app
ENV NODE_ENV=production

# Production dependencies only. `prepare` (svelte-kit sync) is written to
# tolerate its own absence here, which is why this does not need --ignore-scripts.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY --from=build /app/build ./build

USER node
EXPOSE 3071
ENV PORT=3071
CMD ["node", "build"]
