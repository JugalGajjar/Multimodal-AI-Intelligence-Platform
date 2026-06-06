"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

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
import { fetchCurrentUser, resendVerification, verifyEmail } from "@/lib/auth-api";
import { useAuthStore } from "@/store/auth";

export function VerifyEmailForm() {
  const router = useRouter();
  const search = useSearchParams();
  const setSession = useAuthStore((s) => s.setSession);

  const [email, setEmail] = useState(search.get("email") ?? "");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [resending, setResending] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setInfo(null);
    setSubmitting(true);
    try {
      const { access_token } = await verifyEmail(email, code.trim().toUpperCase());
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
        setError("Verification failed. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function onResend() {
    if (!email) {
      setError("Enter your email first.");
      return;
    }
    setError(null);
    setInfo(null);
    setResending(true);
    try {
      const resp = await resendVerification(email);
      setInfo(resp.message);
    } catch {
      setError("Couldn't resend the code. Try again.");
    } finally {
      setResending(false);
    }
  }

  return (
    <Card className="glass w-full max-w-md py-7">
      <CardHeader className="space-y-2 px-5 pb-2 sm:px-7">
        <CardTitle className="text-2xl">Verify your email</CardTitle>
        <CardDescription className="mt-1">
          Enter the 8-character code we sent to your inbox.
        </CardDescription>
      </CardHeader>
      <form onSubmit={onSubmit}>
        <CardContent className="space-y-5 px-5 pt-4 sm:px-7">
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
            <Label htmlFor="code">Verification code</Label>
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
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          {info && (
            <p role="status" className="text-sm text-muted-foreground">
              {info}
            </p>
          )}
        </CardContent>
        <CardFooter className="mt-5 flex flex-col gap-4 px-5 pt-5 sm:flex-row sm:items-center sm:justify-between sm:px-7">
          <button
            type="button"
            onClick={onResend}
            disabled={resending}
            className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground disabled:opacity-50"
          >
            {resending ? "Sending…" : "Resend code"}
          </button>
          <Button
            type="submit"
            disabled={submitting}
            className="h-11 w-full bg-gradient-brand text-brand-foreground glow-brand px-6 sm:w-auto"
          >
            {submitting ? "Verifying…" : "Verify"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
