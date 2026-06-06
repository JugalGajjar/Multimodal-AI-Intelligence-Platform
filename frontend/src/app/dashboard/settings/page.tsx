"use client";

import { KeyRound, LogOut, Settings as SettingsIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { AuthGate } from "@/components/auth-gate";
import { AppShell } from "@/components/layout/app-shell";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuthStore } from "@/store/auth";

export default function SettingsPage() {
  return (
    <AuthGate>
      <AppShell>
        <SettingsInner />
      </AppShell>
    </AuthGate>
  );
}

function SettingsInner() {
  const router = useRouter();
  const user = useAuthStore((s) => s.user);
  const clearSession = useAuthStore((s) => s.clearSession);

  function onLogout() {
    clearSession();
    router.replace("/login");
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
      <header className="flex flex-col gap-2">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          Workspace
        </p>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight sm:text-3xl">
          <SettingsIcon
            className="size-6 text-[color:var(--brand)]"
            aria-hidden="true"
          />
          Settings
        </h1>
        <p className="text-sm text-muted-foreground">
          {user?.email ? (
            <>
              Signed in as <span className="font-medium">{user.email}</span>.
            </>
          ) : (
            "Account preferences."
          )}
        </p>
      </header>

      <Card className="glass">
        <CardHeader>
          <CardTitle className="text-base">Appearance</CardTitle>
          <CardDescription>Switch between light and dark mode.</CardDescription>
        </CardHeader>
        <CardContent>
          <ThemeToggle />
        </CardContent>
      </Card>

      <Card className="glass">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <KeyRound className="size-4" aria-hidden="true" />
            Change password
          </CardTitle>
          <CardDescription>
            We&rsquo;ll send a one-time code to your email so you can set a new
            password.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link
            href={`/forgot-password${
              user?.email ? `?email=${encodeURIComponent(user.email)}` : ""
            }`}
          >
            <Button variant="outline" size="sm">
              Send reset code
            </Button>
          </Link>
        </CardContent>
      </Card>

      <Card className="glass border-destructive/30">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <LogOut className="size-4 text-destructive" aria-hidden="true" />
            Sign out
          </CardTitle>
          <CardDescription>
            End your session on this device. You can sign back in any time.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="destructive" size="sm" onClick={onLogout}>
            Sign out
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
