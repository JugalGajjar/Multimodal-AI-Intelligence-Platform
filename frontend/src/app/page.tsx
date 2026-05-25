import { HealthStatus } from "@/components/health-status";

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
      <HealthStatus />
    </main>
  );
}
