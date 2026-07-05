import { ArrowRight, FileText, Image as ImageIcon, Mic, Network } from "lucide-react";
import Link from "next/link";

import { BrandMark } from "@/components/layout/brand-mark";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { buttonVariants } from "@/components/ui/button";

const FEATURES = [
  {
    Icon: FileText,
    title: "Multimodal ingest",
    body: "PDFs, Word, PowerPoint, images, audio, video, and text. All in one shared library you can chat over.",
  },
  {
    Icon: ImageIcon,
    title: "Vision + OCR",
    body: "Every image is turned into searchable text and a short description of what is shown.",
  },
  {
    Icon: Mic,
    title: "Audio transcription",
    body: "Meetings and voice notes become citable text you can chat with.",
  },
  {
    Icon: Network,
    title: "Knowledge graph",
    body: "Entities and relationships pulled from your docs, visualized and used to ground answers.",
  },
];

export default function Home() {
  return (
    // Mobile grows naturally (min-h-svh). Desktop (lg+) is locked to the
    // viewport so the whole page fits without scroll.
    <div className="flex min-h-svh flex-col lg:h-svh lg:overflow-hidden">
      <header className="flex shrink-0 items-center justify-between px-6 py-5 sm:px-10">
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

      <main className="flex flex-1 flex-col items-center justify-center gap-10 px-6 pb-10 sm:gap-14 sm:pb-16 lg:gap-10 lg:pb-8">
        <section className="flex max-w-3xl flex-col items-center gap-6 text-center">
          <h1 className="text-3xl font-semibold leading-[1.1] tracking-tight sm:text-5xl lg:text-6xl">
            Chat with everything
            <br />
            <span className="text-gradient-brand">you&rsquo;ve ever uploaded.</span>
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">
            Multimodal RAG over text, PDFs, Word, PowerPoint, images, audio,
            and video, with a live knowledge graph and grounded, cited
            answers.
          </p>

          <div className="mt-2 flex flex-col items-center gap-3 sm:flex-row sm:gap-4">
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

        <section className="grid w-full max-w-5xl gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {FEATURES.map(({ Icon, title, body }) => (
            <article
              key={title}
              className="glass group rounded-xl p-5 transition-transform hover:-translate-y-1"
            >
              <span
                aria-hidden="true"
                className="mb-3 inline-flex size-9 items-center justify-center rounded-lg bg-gradient-brand text-brand-foreground glow-brand"
              >
                <Icon className="size-4" />
              </span>
              <h3 className="text-sm font-semibold">{title}</h3>
              <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                {body}
              </p>
            </article>
          ))}
        </section>
      </main>
    </div>
  );
}
