"use client";

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
import { ApiError } from "@/lib/api";
import { fetchCurrentUser, loginUser } from "@/lib/auth-api";
import { useAuthStore } from "@/store/auth";

export function LoginForm() {
  const router = useRouter();
  const setSession = useAuthStore((s) => s.setSession);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { access_token } = await loginUser(email, password);
      const user = await fetchCurrentUser(access_token);
      setSession({ id: user.id, email: user.email }, access_token);
      router.push("/dashboard");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Invalid email or password.");
      } else {
        setError("Login failed. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card className="glass w-full max-w-md py-7">
      <CardHeader className="space-y-2 px-7 pb-2">
        <CardTitle className="text-2xl">Welcome back</CardTitle>
        <CardDescription className="mt-1">
          Sign in to your{" "}
          <span className="text-gradient-brand font-medium">MMAP</span>{" "}
          workspace.
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
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
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
            href="/register"
            className="text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
          >
            Create an account
          </a>
          <Button
            type="submit"
            disabled={submitting}
            className="h-11 w-full bg-gradient-brand text-brand-foreground glow-brand px-6 sm:w-auto"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
