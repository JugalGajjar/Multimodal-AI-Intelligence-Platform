"use client";

import { useRouter } from "next/navigation";
import { useEffect, useSyncExternalStore, type ReactNode } from "react";

import { useAuthStore } from "@/store/auth";

/**
 * Client-side auth gate. Renders children only after Zustand has rehydrated
 * from localStorage and a token is present; otherwise redirects to /login.
 *
 * `hydrated` is derived via useSyncExternalStore so we avoid the
 * set-state-in-effect anti-pattern (React 19+).
 */
function useHydrated(): boolean {
  return useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
}

export function AuthGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const token = useAuthStore((s) => s.token);
  const hydrated = useHydrated();

  useEffect(() => {
    if (hydrated && !token) {
      router.replace("/login");
    }
  }, [hydrated, token, router]);

  if (!hydrated || !token) return null;
  return <>{children}</>;
}
