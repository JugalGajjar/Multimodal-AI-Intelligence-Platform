import { ArrowRight, FileText, Image as ImageIcon, Mic, Network } from "lucide-react";
import Link from "next/link";

import { BrandMark } from "@/components/layout/brand-mark";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { buttonVariants } from "@/components/ui/button";

const FEATURES = [
  {
    Icon: FileText,
    title: "Multimodal ingest",
    body: "PDFs, images, audio, video, and text. All extracted, chunked, and embedded into a shared vector space.",
  },
  {
    Icon: ImageIcon,
    title: "Vision + OCR",
    body: "RapidOCR + a vision-language model give every image a searchable, summarized representation.",
  },
  {
    Icon: Mic,
    title: "Audio transcription",
    body: "Groq Whisper turns recordings into citable, retrievable text. Instantly.",
  },
  {
    Icon: Network,
    title: "Knowledge graph",
    body: "Entities and relationships extracted from your docs, visualized and used to ground answers.",
  },
];

export default function Home() {
  return (
    <div className="flex min-h-svh flex-col">
      <header className="flex items-center justify-between px-6 py-5 sm:px-10">
        <BrandMark size="md" />
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <Link
            href="/login"
            className={buttonVariants({ variant: "ghost", size: "sm" })}
          >
            Sign in
          </Link>
        </div>
      </header>

      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16 sm:py-24">
        <section className="flex max-w-3xl flex-col items-center gap-8 text-center">
          <h1 className="text-4xl font-semibold leading-[1.1] tracking-tight sm:text-6xl">
            Chat with everything
            <br />
            <span className="text-gradient-brand">you’ve ever uploaded.</span>
          </h1>
          <p className="max-w-2xl text-base leading-relaxed text-muted-foreground sm:text-lg">
            Multimodal RAG over text, images, PDFs, audio, and video, with a
            live knowledge graph and grounded, cited answers.
          </p>

          <div className="mt-4 flex flex-col items-center gap-3 sm:flex-row sm:gap-4">
            <Link
              href="/register"
              className={
                buttonVariants({ size: "lg" }) +
                " bg-gradient-brand text-brand-foreground glow-brand px-7 transition-transform hover:-translate-y-0.5"
              }
            >
              Get started
              <ArrowRight className="ml-1.5 size-4" aria-hidden="true" />
            </Link>
            <Link
              href="/login"
              className={
                buttonVariants({ variant: "outline", size: "lg" }) + " px-7"
              }
            >
              I already have an account
            </Link>
          </div>
        </section>

        <section className="mt-20 grid w-full max-w-5xl gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map(({ Icon, title, body }) => (
            <article
              key={title}
              className="glass group rounded-xl p-6 transition-transform hover:-translate-y-1"
            >
              <span
                aria-hidden="true"
                className="mb-4 inline-flex size-10 items-center justify-center rounded-lg bg-gradient-brand text-brand-foreground glow-brand"
              >
                <Icon className="size-4" />
              </span>
              <h3 className="text-sm font-semibold">{title}</h3>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                {body}
              </p>
            </article>
          ))}
        </section>
      </main>
    </div>
  );
}
