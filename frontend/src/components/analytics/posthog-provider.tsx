"use client";

import { usePathname, useSearchParams } from "next/navigation";
import posthog from "posthog-js";
import { Suspense, useEffect, useRef, type ReactNode } from "react";

import { useAuthStore } from "@/store/auth";

const POSTHOG_KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY;
const POSTHOG_HOST =
  process.env.NEXT_PUBLIC_POSTHOG_HOST ?? "https://us.i.posthog.com";

let initialized = false;

function ensureInit(): boolean {
  if (typeof window === "undefined" || !POSTHOG_KEY) return false;
  if (initialized) return true;
  posthog.init(POSTHOG_KEY, {
    api_host: POSTHOG_HOST,
    person_profiles: "identified_only",
    // We capture pageviews manually below — App Router's client transitions
    // don't fire a full-page load, so the SDK's auto pageview misses them.
    capture_pageview: false,
  });
  initialized = true;
  return true;
}

function PostHogPageView() {
  const pathname = usePathname();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (!ensureInit() || !pathname) return;
    const qs = searchParams?.toString();
    const url = qs
      ? `${window.location.origin}${pathname}?${qs}`
      : `${window.location.origin}${pathname}`;
    posthog.capture("$pageview", { $current_url: url });
  }, [pathname, searchParams]);

  return null;
}

function PostHogIdentity() {
  const user = useAuthStore((s) => s.user);
  const previousId = useRef<string | null>(null);

  useEffect(() => {
    if (!ensureInit()) return;
    const id = user?.id ?? null;
    if (id && id !== previousId.current) {
      posthog.identify(id, user?.email ? { email: user.email } : undefined);
      previousId.current = id;
    } else if (!id && previousId.current) {
      posthog.reset();
      previousId.current = null;
    }
  }, [user?.id, user?.email]);

  return null;
}

export function PostHogProvider({ children }: { children: ReactNode }) {
  return (
    <>
      {/* useSearchParams must sit under a Suspense boundary in App Router. */}
      <Suspense fallback={null}>
        <PostHogPageView />
      </Suspense>
      <PostHogIdentity />
      {children}
    </>
  );
}
