"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { PasswordStrength } from "@/components/auth/password-strength";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { fetchCurrentUser, resetPassword } from "@/lib/auth-api";
import { firstPasswordError } from "@/lib/password-validator";
import { useAuthStore } from "@/store/auth";

export function ResetPasswordForm() {
  const router = useRouter();
  const search = useSearchParams();
  const setSession = useAuthStore((s) => s.setSession);

  const [email, setEmail] = useState(search.get("email") ?? "");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const pwError = firstPasswordError(password, email);
    if (pwError) {
      setError(pwError);
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      const { access_token } = await resetPassword(
        email,
        code.trim().toUpperCase(),
        password,
      );
      const user = await fetchCurrentUser(access_token);
      setSession(
        {
          id: user.id,
          email: user.email,
          isVerified: user.is_verified,
          firstName: user.first_name,
          lastName: user.last_name,
        },
        access_token,
      );
      router.push("/dashboard");
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setError("Invalid or expired code.");
      } else {
        setError("Couldn't reset your password. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card className="glass w-full max-w-md py-7">
      <CardHeader className="space-y-2 px-7 pb-2">
        <CardTitle className="text-2xl">Set a new password</CardTitle>
        <CardDescription className="mt-1">
          Enter the code you received and choose a new password.
        </CardDescription>
      </CardHeader>
      <form onSubmit={onSubmit}>
        <CardContent className="space-y-5 px-7 pt-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="h-11 px-4"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="code">Reset code</Label>
            <Input
              id="code"
              type="text"
              inputMode="text"
              autoComplete="one-time-code"
              maxLength={8}
              minLength={8}
              required
              value={code}
              onChange={(e) =>
                setCode(e.target.value.replace(/\s/g, "").toUpperCase())
              }
              placeholder="ABCD1234"
              className="h-11 px-4 font-mono tracking-widest uppercase"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">New password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              minLength={8}
              maxLength={32}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="8 to 32 characters"
              className="h-11 px-4"
            />
            <PasswordStrength password={password} email={email} className="pt-1" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="confirm">Confirm new password</Label>
            <Input
              id="confirm"
              type="password"
              autoComplete="new-password"
              minLength={8}
              maxLength={32}
              required
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Repeat your new password"
              className="h-11 px-4"
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </CardContent>
        <CardFooter className="mt-5 flex flex-col gap-4 px-7 pt-5 sm:flex-row sm:items-center sm:justify-between">
          <a
            href="/login"
            className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
          >
            Back to sign in
          </a>
          <Button
            type="submit"
            disabled={submitting}
            className="h-11 w-full bg-gradient-brand text-brand-foreground glow-brand px-6 sm:w-auto"
          >
            {submitting ? "Saving…" : "Reset password"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
