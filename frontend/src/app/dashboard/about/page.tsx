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
                  and drop in a file. PDFs, Word documents (.docx), PowerPoint
                  decks (.pptx), images, audio (mp3, wav), video (mp4, webm,
                  mov up to five minutes), or plain text and markdown. The
                  cap is 100 MB per file.
                </li>
                <li>
                  Wait for the status badge to flip to{" "}
                  <em>processed</em>. Big files take longer because the worker
                  is doing OCR, Whisper, and embedding in the background. If
                  it flips to <em>failed</em>, hover the badge to read why
                  and try a smaller or text-based version of the file.
                </li>
                <li>
                  Come back to the{" "}
                  <Link
                    href="/dashboard"
                    className="font-medium text-[color:var(--brand)] underline-offset-4 hover:underline"
                  >
                    Dashboard
                  </Link>{" "}
                  and ask a question. Follow ups remember earlier turns, and
                  the thread stays put if you wander off to Documents or
                  Settings and come back.
                </li>
                <li>
                  When you are done, hit <em>New chat</em> to start fresh,
                  or reload the tab. Old conversations live under{" "}
                  <Link
                    href="/dashboard/chats"
                    className="font-medium text-[color:var(--brand)] underline-offset-4 hover:underline"
                  >
                    Chats
                  </Link>
                  , where you can search across titles, summaries, and
                  message text, rename a thread, or delete it. Opening an
                  old chat shows the full transcript with citations
                  intact, and the <em>Continue</em> button loads that
                  thread back onto the dashboard so your next question
                  appends to it.
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
                  <strong>Pick your own answer model.</strong> Settings
                  also has an <em>Answer model</em> dropdown. Leave it on{" "}
                  <em>Default</em> to follow the app-wide setting, or pick
                  a specific open source model (GPT-OSS 120B, GPT-OSS 20B,
                  Qwen3 32B) for your account. The badge above every answer
                  reflects the model that actually replied, so it is easy
                  to compare.
                </li>
                <li>
                  <strong>You can stop a slow answer.</strong> While the
                  response is streaming, the send button turns into a stop
                  icon. Click it if the model is going somewhere you did not
                  want. Your question comes back into the box so you can
                  rephrase and try again.
                </li>
                <li>
                  <strong>Citations that actually match.</strong> Under each
                  answer the citation preview is centered on the words from
                  your question, not the first line of the chunk. If a
                  citation looks off, the snippet usually makes it obvious
                  why.
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
                  <strong>Reading.</strong> RapidOCR for images, Whisper
                  Large v3 Turbo on Groq for audio, native parse for PDFs,
                  Word, PowerPoint, and plain text. Video samples up to 30
                  adaptive frames plus the audio track, then feeds all of
                  it into a single Nemotron Nano 2 VL call so the model
                  can cross reference what is said against what is shown.
                  PowerPoint slides are chunked per slide and speaker
                  notes are preserved so citations point at the exact
                  slide the answer came from.
                </li>
                <li>
                  <strong>Indexing.</strong> Each chunk is embedded twice.
                  Once as a dense vector with sentence-transformers
                  (bge-small-en-v1.5, 384 dims) and once as a sparse BM25
                  vector. Qdrant fuses the two via reciprocal rank at query
                  time, so keyword hits and semantic hits both surface. A
                  cross encoder reranker (bge-reranker-base) then re-scores
                  the top candidates against the exact question, so the
                  chunk that answers you wins and not just the topically
                  nearest one. Anything under 80 alphanumeric characters
                  gets dropped at ingest so OCR noise never lands in the
                  index. Neo4j AuraDB holds the entity graph on the side.
                </li>
                <li>
                  <strong>Reasoning.</strong> Chat answers come from Groq,
                  defaulting to GPT-OSS 120B. In Settings you can switch
                  to GPT-OSS 20B or Qwen3 32B for your account; the badge
                  above every answer shows which model actually replied.
                  Entity extraction, chat summarization, intent routing,
                  and answer verification also run on GPT-OSS 120B. All
                  Groq calls hit free tier endpoints so an idle account
                  costs nothing.
                </li>
                <li>
                  <strong>Verifying.</strong> Every answer is checked
                  against the cited context (and web sources when the Web
                  toggle is on) by a separate model. The score is shown on
                  the badge above the response, and any claims that could
                  not be grounded get flagged inline.
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
