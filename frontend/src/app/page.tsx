import Link from "next/link";

import { HealthStatus } from "@/components/health-status";
import { buttonVariants } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-8 px-6 py-16">
      <div className="flex max-w-2xl flex-col items-center gap-3 text-center">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
          Multimodal AI Intelligence Platform
        </h1>
        <p className="text-muted-foreground">
          Multimodal RAG over text, images, PDFs, and audio — with knowledge
          graphs and agentic reasoning.
        </p>
      </div>
      <div className="flex gap-3">
        <Link href="/register" className={buttonVariants()}>
          Get started
        </Link>
        <Link href="/login" className={buttonVariants({ variant: "outline" })}>
          Sign in
        </Link>
      </div>
      <HealthStatus />
    </main>
  );
}
