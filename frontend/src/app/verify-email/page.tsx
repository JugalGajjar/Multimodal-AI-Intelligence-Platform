import { Suspense } from "react";

import { VerifyEmailForm } from "@/components/auth/verify-email-form";
import { AuthShell } from "@/components/layout/auth-shell";

export default function VerifyEmailPage() {
  return (
    <AuthShell>
      <Suspense>
        <VerifyEmailForm />
      </Suspense>
    </AuthShell>
  );
}
