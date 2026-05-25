FROM node:22-alpine

WORKDIR /app

ENV NODE_ENV=development \
    NEXT_TELEMETRY_DISABLED=1 \
    PATH=/app/node_modules/.bin:$PATH

RUN apk add --no-cache wget

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=20 \
    CMD wget -qO- http://localhost:3000 >/dev/null || exit 1

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]
