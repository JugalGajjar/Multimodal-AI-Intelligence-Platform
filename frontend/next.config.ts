import type { NextConfig } from "next";

// Defensive headers applied to every response.
// CSP needs to allow:
//  - 'self' for our own JS/CSS
//  - inline script/style (React hydration + Tailwind runtime classes)
//  - the backend API origin for fetch() — configured via NEXT_PUBLIC_API_URL
//  - PostHog origins when analytics/session-recording are configured:
//      • connect-src: event ingestion + config /decide endpoint
//      • script-src: rrweb recorder.js is loaded remotely from the assets host
//        when session recording is on
//      • img-src: heatmap / canvas capture uses data: pixels from PostHog
//      • worker-src 'self' blob:: rrweb compresses recording chunks in a
//        blob-URL web worker — blocked by default under strict CSP
const apiOrigin = (() => {
  const raw = process.env.NEXT_PUBLIC_API_URL?.trim() || "http://localhost:8000";
  try {
    const u = new URL(raw);
    return `${u.protocol}//${u.host}`;
  } catch {
    return raw;
  }
})();

// PostHog Cloud regions publish assets on a sibling `-assets` subdomain:
//   us.i.posthog.com     → us-assets.i.posthog.com
//   eu.i.posthog.com     → eu-assets.i.posthog.com
// We derive both so eu-hosted projects work with no extra config.
// Gated on KEY presence (matches the provider) and falls back to the same
// default host the provider uses — otherwise a build with KEY set but HOST
// unset produces an asymmetric CSP that blocks the loaded PostHog script.
const posthogOrigins = (() => {
  if (!process.env.NEXT_PUBLIC_POSTHOG_KEY?.trim()) return [] as string[];
  const rawHost =
    process.env.NEXT_PUBLIC_POSTHOG_HOST?.trim() || "https://us.i.posthog.com";
  try {
    const u = new URL(rawHost);
    const eventOrigin = `${u.protocol}//${u.host}`;
    const assetsHost = u.host.replace(".i.posthog.com", "-assets.i.posthog.com");
    const assetsOrigin = `${u.protocol}//${assetsHost}`;
    return assetsOrigin === eventOrigin
      ? [eventOrigin]
      : [eventOrigin, assetsOrigin];
  } catch {
    return [] as string[];
  }
})();

const posthogConfigured = posthogOrigins.length > 0;

const connectSources = ["'self'", apiOrigin, ...posthogOrigins].join(" ");
const scriptSources = ["'self'", "'unsafe-inline'", ...posthogOrigins].join(" ");
const imgSources = ["'self'", "data:", "blob:", ...posthogOrigins].join(" ");

const cspDirectives = [
  "default-src 'self'",
  `script-src ${scriptSources}`,
  "style-src 'self' 'unsafe-inline'",
  `img-src ${imgSources}`,
  "font-src 'self' data:",
  `connect-src ${connectSources}`,
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
];
if (posthogConfigured) {
  // rrweb (used by PostHog session recording) instantiates its compression
  // worker from a Blob URL — `worker-src 'self' blob:` unblocks that path.
  // Not added when PostHog is unset, so dev/preview keep the tighter default.
  cspDirectives.push("worker-src 'self' blob:");
}
const CSP = cspDirectives.join("; ");

const SECURITY_HEADERS = [
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "same-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=()",
  },
  { key: "Content-Security-Policy", value: CSP },
];

const nextConfig: NextConfig = {
  // Self-contained server.js bundle in .next/standalone; lets the production
  // image run without node_modules at runtime.
  output: "standalone",
  async headers() {
    return [
      {
        source: "/:path*",
        headers: SECURITY_HEADERS,
      },
    ];
  },
};

export default nextConfig;
