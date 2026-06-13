"use client";

import {
  BookOpen,
  Database,
  FileText,
  Globe,
  MessageSquareText,
  Network,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import Link from "next/link";

import { AuthGate } from "@/components/auth-gate";
import { AppShell } from "@/components/layout/app-shell";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function AboutPage() {
  return (
    <AuthGate>
      <AppShell>
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
          <header className="flex flex-col gap-2">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Workspace
            </p>
            <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight sm:text-3xl">
              <BookOpen
                className="size-6 text-[color:var(--brand)]"
                aria-hidden="true"
              />
              About MMAP
            </h1>
            <p className="text-sm leading-relaxed text-muted-foreground">
              A short guide to what this is, why it was built, and how to get
              the most out of it.
            </p>
          </header>

          <Section
            Icon={Sparkles}
            title="What it is"
            body={
              <>
                <p>
                  MMAP (the Multimodal AI Intelligence Platform) lets you chat
                  with everything you upload. Drop in a PDF, an audio note, a
                  screenshot, a meeting recording, or a video, and it will
                  read, transcribe, watch, and remember.
                </p>
                <p>
                  Every answer cites the exact chunk it came from, and a live
                  knowledge graph grows in the background as you add more
                  material, so you can see how ideas in your library connect.
                </p>
              </>
            }
          />

          <Section
            Icon={MessageSquareText}
            title="Why it exists"
            body={
              <>
                <p>
                  Large language models are great at writing and bad at
                  remembering specifics. They will confidently invent a quote,
                  miscite a study, or describe a chart they cannot see. The
                  fix is to give them your real material and force them to
                  point at the sentences they used.
                </p>
                <p>
                  MMAP was built so a single person, not a team with a
                  Kubernetes cluster, can run a real grounded RAG stack over
                  their own work, for free, with citations that actually point
                  somewhere.
                </p>
              </>
            }
          />

          <Section
            Icon={ShieldCheck}
            title="How it compares"
            body={
              <ul className="space-y-3 text-sm leading-relaxed">
                <li>
                  <strong>ChatGPT or Claude with attachments.</strong> Great
                  for a one off question on a single file. They do not keep a
                  durable index, they cannot show you which chunk a sentence
                  came from, and most plans cap file types or sizes.
                </li>
                <li>
                  <strong>NotebookLM.</strong> Closest in spirit. Strong for
                  text and PDFs, but no audio or video ingest, no editable
                  knowledge graph, and your library lives inside someone
                  else&apos;s account.
                </li>
                <li>
                  <strong>Self hosted LangChain notebooks.</strong> Powerful
                  but you assemble the chunking, the embeddings, the vector
                  store, the citation handling, and the UI yourself. MMAP
                  ships all of that, including OCR and Whisper.
                </li>
                <li>
                  <strong>Paid enterprise RAG.</strong> Polished but priced
                  for companies. MMAP runs on free tier infrastructure and
                  the source is yours.
                </li>
              </ul>
            }
          />

          <Section
            Icon={FileText}
            title="How to use it"
            body={
              <ol className="list-decimal space-y-3 pl-5 text-sm leading-relaxed marker:text-[color:var(--brand)]">
                <li>
                  Go to{" "}
                  <Link
                    href="/dashboard/documents"
                    className="font-medium text-[color:var(--brand)] underline-offset-4 hover:underline"
                  >
                    Your documents
                  </Link>{" "}
                  and drop in a file. PDFs, images, audio (mp3, wav), video
                  (mp4, webm, mov up to five minutes), or plain text and
                  markdown. The cap is 100 MB per file.
                </li>
                <li>
                  Wait for the status badge to flip to{" "}
                  <em>processed</em>. Big files take longer because the worker
                  is doing OCR, Whisper, and embedding in the background.
                </li>
                <li>
                  Come back to the{" "}
                  <Link
                    href="/dashboard"
                    className="font-medium text-[color:var(--brand)] underline-offset-4 hover:underline"
                  >
                    Dashboard
                  </Link>{" "}
                  and ask a question. Follow ups remember earlier turns.
                </li>
                <li>
                  When you are done, hit <em>New chat</em> to start fresh, or
                  reload the tab. Old conversations live under{" "}
                  <Link
                    href="/dashboard/chats"
                    className="font-medium text-[color:var(--brand)] underline-offset-4 hover:underline"
                  >
                    Chats
                  </Link>
                  , where you can search, rename, or delete them.
                </li>
              </ol>
            }
          />

          <Section
            Icon={Database}
            title="Getting the most out of it"
            body={
              <ul className="space-y-3 text-sm leading-relaxed">
                <li>
                  <strong>Two toggles next to the send button.</strong>{" "}
                  <em>RAG</em> on means the answer is grounded in your
                  uploads. RAG off means the model answers from its own
                  knowledge, useful for things your library does not cover.{" "}
                  <em>Web</em> on pulls a handful of fresh web results
                  through Tavily and cites them inline.
                </li>
                <li>
                  <strong>Strict vs regular mode.</strong> In{" "}
                  <Link
                    href="/dashboard/settings"
                    className="font-medium text-[color:var(--brand)] underline-offset-4 hover:underline"
                  >
                    Settings
                  </Link>{" "}
                  pick strict if you want the answer withheld whenever the
                  groundedness score is low. Pick regular if you want a
                  hybrid that blends documents with general knowledge and is
                  honest about which is which.
                </li>
                <li>
                  <strong>Use good filenames.</strong> The title of the chat
                  and the summary panel both pull from filenames first, so a
                  document called <em>q3-board-deck.pdf</em> is easier to
                  spot in a list than <em>scan_0042.pdf</em>.
                </li>
                <li>
                  <strong>Group related material.</strong> Upload the whole
                  set in one go. The knowledge graph gets more interesting
                  when entities overlap across documents.
                </li>
                <li>
                  <strong>Audio and video carry the spoken track.</strong>{" "}
                  Whisper turns spoken sentences into citable text, so a
                  meeting recording becomes searchable the same way a memo
                  does.
                </li>
                <li>
                  <strong>Web augment for time sensitive answers.</strong>{" "}
                  Toggle <em>Web</em> on when the question depends on facts
                  that change, like a stable version number or a recent
                  release.
                </li>
              </ul>
            }
          />

          <Section
            Icon={Network}
            title="Under the hood, briefly"
            body={
              <ul className="space-y-2 text-sm leading-relaxed">
                <li>
                  <strong>Reading.</strong> RapidOCR for images, Whisper Large
                  v3 Turbo on Groq for audio, Nemotron Nano 2 VL on OpenRouter
                  for video frames and PDFs, plus native parse for text.
                </li>
                <li>
                  <strong>Indexing.</strong> sentence-transformers
                  (bge-small-en-v1.5, 384 dims) into Qdrant for vector search,
                  and Neo4j AuraDB for the entity graph.
                </li>
                <li>
                  <strong>Reasoning.</strong> DeepSeek for the main answer,
                  Llama 3.3 70B for entity and structured extraction, both
                  through cheap free tier endpoints.
                </li>
                <li>
                  <strong>Verifying.</strong> Every answer is checked against
                  the cited context by a separate model, and the score is
                  shown on the badge above the response.
                </li>
              </ul>
            }
          />

          <Section
            Icon={Globe}
            title="One more thing"
            body={
              <p className="text-sm leading-relaxed">
                MMAP is open source. If you find a sharp edge, the repo lives
                on GitHub and a pull request is the fastest way to make it
                better.
              </p>
            }
          />
        </div>
      </AppShell>
    </AuthGate>
  );
}

function Section({
  Icon,
  title,
  body,
}: {
  Icon: typeof Sparkles;
  title: string;
  body: React.ReactNode;
}) {
  return (
    <Card className="glass">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className="size-4 text-[color:var(--brand)]" aria-hidden="true" />
          {title}
        </CardTitle>
        <CardDescription className="sr-only">{title}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-relaxed text-foreground/90">
        {body}
      </CardContent>
    </Card>
  );
}
