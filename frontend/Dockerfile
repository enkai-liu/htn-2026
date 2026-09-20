# The Next.js server for Railway (or any container host). Build context is frontend/.
# It has to be a server, not the static export: /runs/<id> is rendered on demand.
FROM node:22-slim
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
# the version package.json's packageManager pins; installed directly rather than through corepack's key checks
RUN npm install -g pnpm@11.9.0
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
# NEXT_PUBLIC_* is inlined by `next build`, so the API's address is a build argument, not a runtime variable.
# Railway passes a service variable of the same name. Unset would build a site that calls itself: fail instead.
ARG NEXT_PUBLIC_API_BASE
RUN test -n "$NEXT_PUBLIC_API_BASE" || (echo "NEXT_PUBLIC_API_BASE is not set: point it at the API's public URL" >&2; exit 1)
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
RUN pnpm build
# `next start` listens on $PORT, which the host assigns
CMD ["pnpm", "start"]
