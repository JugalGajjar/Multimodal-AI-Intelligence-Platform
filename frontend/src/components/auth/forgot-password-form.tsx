"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
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
import { forgotPassword } from "@/lib/auth-api";

export function ForgotPasswordForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await forgotPassword(email);
      // Always advance to /reset-password — the backend deliberately
      // doesn't tell us whether the email exists.
      router.push(`/reset-password?email=${encodeURIComponent(email)}`);
    } catch {
      setError("Couldn't start the reset. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card className="glass w-full max-w-md py-7">
      <CardHeader className="space-y-2 px-5 pb-2 sm:px-7">
        <CardTitle className="text-2xl">Reset your password</CardTitle>
        <CardDescription className="mt-1">
          Enter your email and we&rsquo;ll send a reset code if an account exists.
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
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
        </CardContent>
        <CardFooter className="mt-5 flex flex-col gap-4 px-5 pt-5 sm:flex-row sm:items-center sm:justify-between sm:px-7">
          <Link
            href="/login"
            className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
          >
            Back to sign in
          </Link>
          <Button
            type="submit"
            disabled={submitting}
            className="h-11 w-full bg-gradient-brand text-brand-foreground glow-brand px-6 sm:w-auto"
          >
            {submitting ? "Sending…" : "Send code"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
