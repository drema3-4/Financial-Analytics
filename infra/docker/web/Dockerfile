# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
FROM node:24.21.0-alpine3.23@sha256:9ec4a2e289874ed0d722e1772ec2de45d2801541db8612f3638b26f128c69ac2 AS builder

WORKDIR /workspace

RUN npm install --global "pnpm@12.12.1"

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.json ./
COPY apps/web ./apps/web
COPY packages/frontend/api ./packages/frontend/api
RUN pnpm install --frozen-lockfile

ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN pnpm --filter @financial-analytics/web build

FROM node:24.21.0-alpine3.23@sha256:9ec4a2e289874ed0d722e1772ec2de45d2801541db8612f3638b26f128c69ac2 AS runtime

ENV NODE_ENV=production \
    PORT=4173

WORKDIR /app

RUN apk upgrade --no-cache \
    && rm -rf /usr/local/lib/node_modules/npm \
    && rm -f /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack

COPY --chown=node:node --from=builder /workspace/apps/web/dist ./dist
COPY --chown=node:node infra/docker/web/server.mjs ./server.mjs

USER node

EXPOSE 4173

CMD ["node", "server.mjs"]
