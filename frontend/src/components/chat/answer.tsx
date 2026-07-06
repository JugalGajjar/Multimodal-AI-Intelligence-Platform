"use client";

import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Globe,
  Network,
  Route,
  ScrollText,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";

// Model output is not trusted — it can carry prompt-injection-crafted HTML
// (script tags, iframes, on* handlers, javascript: URLs). Parse the raw HTML
// the model produced (via rehype-raw so <br>, <em>, tables etc. render
// natively), then run it through rehype-sanitize with an explicit allowlist
// of tags that render nicely and can't be weaponised.
//
// The allowlist starts from rehype-sanitize's defaultSchema (github-flavoured,
// widely audited) and only widens what's necessary for typical model output:
// explicitly include <br> so hard line breaks land, and allow className on
// <span>/<code> so any future syntax highlighter can style tokens. All
// <script>/<iframe>/<object>/<embed>, event-handler attrs, and non-http(s)
// URL schemes stay blocked by the defaultSchema.
const answerSanitizeSchema: typeof defaultSchema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), "br"],
  attributes: {
    ...(defaultSchema.attributes ?? {}),
    span: [...(defaultSchema.attributes?.span ?? []), "className"],
    code: [...(defaultSchema.attributes?.code ?? []), "className"],
  },
};

// Some models (notably Qwen and other CJK-tuned checkpoints) sometimes emit
// citations with full-width brackets 【1】 / 【W1】 or full-width parens
// （1） / （W1） instead of the ASCII [1] / [W1] the prompt asks for. The
// prompt spec is the primary fix; this is a safety net so any drift renders
// consistently and doesn't leak into persisted chat history looking mixed.
// Applied at render time so it also cleans up older chats that were saved
// before the prompt was tightened.
const FULL_WIDTH_CITATION_RE = /[【（]\s*(W?\d+)\s*[】）]/g;
function normalizeCitationBrackets(text: string): string {
  return text.replace(FULL_WIDTH_CITATION_RE, "[$1]");
}

import { KnowledgeGraph } from "@/components/graph/knowledge-graph";
import { Badge } from "@/components/ui/badge";
import {
  type ChatCitation,
  type ChatResponse,
  type ChatVerification,
  type VerificationVerdict,
  type WebCitation,
} from "@/lib/chat-api";
import { chatToGraphProps } from "@/lib/graph-from-chat";

export function Answer({
  response,
  streaming = false,
}: {
  response: ChatResponse;
  streaming?: boolean;
}) {
  const { data: graphData, highlighted, hasGraph } = chatToGraphProps(response);

  return (
    <div className="space-y-5 pt-2" data-testid="chat-answer">
      <div className="flex flex-wrap items-center gap-2">
        {response.model && (
          <Badge variant="outline" className="font-mono text-[10px]">
            {response.model}
          </Badge>
        )}
        {response.intent && response.intent !== "chat" && (
          <IntentBadge intent={response.intent} />
        )}
        {response.used_context ? (
          <Badge className="gap-1 bg-gradient-brand text-brand-foreground">
            <Sparkles className="size-3" aria-hidden="true" />
            used context
          </Badge>
        ) : (
          <Badge variant="outline">no context</Badge>
        )}
        {response.used_graph && (
          <Badge className="gap-1 bg-emerald-500/90 text-white hover:bg-emerald-500 dark:bg-emerald-500/80">
            <Network className="size-3" aria-hidden="true" />
            used graph
          </Badge>
        )}
        {response.used_web && (
          <Badge className="gap-1 bg-sky-500/90 text-white hover:bg-sky-500 dark:bg-sky-500/80">
            <Globe className="size-3" aria-hidden="true" />
            used web
          </Badge>
        )}
        {response.verification && (
          <VerificationBadge verification={response.verification} />
        )}
      </div>

      {response.strict_refusal && (
        <div
          className="flex items-start gap-2.5 rounded-xl border border-amber-500/40 bg-amber-500/5 px-4 py-3 text-xs"
          data-testid="strict-refusal-notice"
        >
          <AlertTriangle
            className="mt-0.5 size-3.5 shrink-0 text-amber-600 dark:text-amber-400"
            aria-hidden="true"
          />
          <span>
            Strict mode withheld this answer — its groundedness score fell
            below the required threshold. The verification badge above shows
            the actual score.
          </span>
        </div>
      )}

      <div className="rounded-xl border border-border/60 bg-background/50 px-4 py-4 text-sm leading-relaxed break-words sm:px-5">
        <div
          className="prose prose-sm dark:prose-invert max-w-none prose-pre:bg-muted/60 prose-pre:text-foreground prose-code:before:content-none prose-code:after:content-none"
          data-testid="chat-answer-text"
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[
              rehypeRaw,
              [rehypeSanitize, answerSanitizeSchema],
            ]}
          >
            {normalizeCitationBrackets(response.answer)}
          </ReactMarkdown>
          {streaming && (
            <span
              aria-hidden="true"
              className="ml-0.5 inline-block h-3.5 w-1.5 -translate-y-px animate-pulse bg-[color:var(--brand)]"
              data-testid="streaming-cursor"
            />
          )}
        </div>
      </div>

      {response.verification &&
        response.verification.verdict !== "skipped" &&
        response.verification.unsupported_claims.length > 0 && (
          <UnsupportedClaimsPanel verification={response.verification} />
        )}

      {/* Citations cite the withheld answer — hide them when refused. */}
      {!response.strict_refusal && response.citations.length > 0 && (
        <div className="space-y-2">
          <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
            Citations
          </p>
          <ol className="space-y-2">
            {response.citations.map((c, i) => (
              <CitationItem key={c.chunk_id} index={i + 1} citation={c} />
            ))}
          </ol>
        </div>
      )}

      {!response.strict_refusal &&
        (response.web_citations?.length ?? 0) > 0 && (
          <div className="space-y-2">
            <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Web sources
            </p>
            <ol className="space-y-2">
              {response.web_citations!.map((w, i) => (
                <WebCitationItem key={w.url} index={i + 1} citation={w} />
              ))}
            </ol>
          </div>
        )}

      {hasGraph && (
        <div className="space-y-2" data-testid="inline-graph">
          <div className="flex items-center justify-between">
            <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Knowledge graph
            </p>
            <Link
              href="/dashboard/graph"
              className="inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-[color:var(--brand)]"
              data-testid="inline-graph-explore-link"
            >
              Explore full graph
              <ArrowUpRight className="size-3" aria-hidden="true" />
            </Link>
          </div>
          <div className="h-[40svh] min-h-[260px] overflow-hidden rounded-xl border border-border/60 bg-background/30 sm:h-[45svh]">
            <KnowledgeGraph
              nodes={graphData.nodes}
              links={graphData.links}
              highlighted={highlighted}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Highlighted nodes are entities the answer mentions by name.
          </p>
        </div>
      )}
    </div>
  );
}

function IntentBadge({ intent }: { intent: string }) {
  const label =
    intent === "summarize"
      ? "summary route"
      : intent === "explain_graph"
        ? "graph route"
        : intent;
  const Icon =
    intent === "summarize" ? ScrollText : intent === "explain_graph" ? Network : Route;
  return (
    <Badge
      variant="outline"
      className="gap-1 border-[color:var(--brand)]/40 text-[color:var(--brand)]"
      title={`Router classified this query as "${intent}"`}
      data-testid="intent-badge"
    >
      <Icon className="size-3" aria-hidden="true" />
      {label}
    </Badge>
  );
}

const VERDICT_STYLES: Record<
  VerificationVerdict,
  { label: string; className: string; Icon: typeof ShieldCheck }
> = {
  verified: {
    label: "verified",
    className: "bg-emerald-500/90 text-white hover:bg-emerald-500",
    Icon: ShieldCheck,
  },
  partial: {
    label: "partial support",
    className: "bg-amber-500/90 text-white hover:bg-amber-500",
    Icon: ShieldAlert,
  },
  unsupported: {
    label: "unsupported",
    className: "bg-red-500/90 text-white hover:bg-red-500",
    Icon: ShieldAlert,
  },
  skipped: {
    label: "not verified",
    className: "",
    Icon: ShieldQuestion,
  },
};

function VerificationBadge({
  verification,
}: {
  verification: ChatVerification;
}) {
  const v = verification.verdict;
  const style = VERDICT_STYLES[v];
  const Icon = style.Icon;
  const pct = Math.round(verification.groundedness_score * 100);
  const counts =
    verification.total_claims > 0
      ? ` · ${verification.supported_claims}/${verification.total_claims}`
      : "";
  const title =
    v === "skipped"
      ? verification.skip_reason || "verification skipped"
      : `groundedness ${pct}%${counts}`;

  if (v === "skipped") {
    return (
      <Badge
        variant="outline"
        className="gap-1 text-muted-foreground"
        title={title}
        data-testid="verification-badge"
      >
        <Icon className="size-3" aria-hidden="true" />
        not verified
      </Badge>
    );
  }

  return (
    <Badge
      className={"gap-1 " + style.className}
      title={title}
      data-testid="verification-badge"
    >
      <Icon className="size-3" aria-hidden="true" />
      {style.label}
      {verification.total_claims > 0 && (
        <span className="ml-0.5 opacity-90">· {pct}%</span>
      )}
    </Badge>
  );
}

function UnsupportedClaimsPanel({
  verification,
}: {
  verification: ChatVerification;
}) {
  const [open, setOpen] = useState(false);
  const count = verification.unsupported_claims.length;

  return (
    <div
      className="rounded-xl border border-amber-500/40 bg-amber-500/5"
      data-testid="unsupported-claims-panel"
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-xs font-medium"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2">
          <AlertTriangle
            className="size-3.5 text-amber-600 dark:text-amber-400"
            aria-hidden="true"
          />
          <span>
            {count} unsupported claim{count === 1 ? "" : "s"}
          </span>
          <span className="font-normal text-muted-foreground">
            (not entailed by the cited context)
          </span>
        </span>
        {open ? (
          <ChevronUp className="size-3.5 text-muted-foreground" aria-hidden="true" />
        ) : (
          <ChevronDown className="size-3.5 text-muted-foreground" aria-hidden="true" />
        )}
      </button>
      {open && (
        <ul
          className="space-y-1.5 border-t border-amber-500/30 px-4 py-3 text-xs text-foreground/90"
          data-testid="unsupported-claims-list"
        >
          {verification.unsupported_claims.map((c, i) => (
            <li key={`${i}-${c.slice(0, 24)}`} className="flex gap-2">
              <CheckCircle2
                className="mt-0.5 size-3 shrink-0 rotate-180 text-muted-foreground"
                aria-hidden="true"
              />
              <span>{c}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function WebCitationItem({
  index,
  citation,
}: {
  index: number;
  citation: WebCitation;
}) {
  let host = "";
  try {
    host = new URL(citation.url).hostname;
  } catch {
    host = citation.url;
  }
  return (
    <li
      className="rounded-lg border border-border/60 bg-background/50 px-3 py-2.5 text-xs"
      data-testid="web-citation-item"
    >
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <a
          href={citation.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex min-w-0 items-center gap-1 font-medium text-foreground/90 transition-colors hover:text-[color:var(--brand)]"
        >
          <span className="font-mono text-[color:var(--brand)]">
            [W{index}]
          </span>
          <span className="truncate">{citation.title || host}</span>
          <ArrowUpRight className="size-3 shrink-0" aria-hidden="true" />
        </a>
        <span className="shrink-0 text-muted-foreground">{host}</span>
      </div>
      {citation.snippet && (
        <p className="text-foreground/80">{citation.snippet}</p>
      )}
    </li>
  );
}

function CitationItem({
  index,
  citation,
}: {
  index: number;
  citation: ChatCitation;
}) {
  return (
    <li
      className="rounded-lg border border-border/60 bg-background/50 px-3 py-2.5 text-xs"
      data-testid="citation-item"
    >
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="font-mono text-muted-foreground">
          <span className="text-[color:var(--brand)]">[{index}]</span> doc{" "}
          {citation.document_id.slice(0, 8)}… · chunk {citation.chunk_index}
        </span>
        <span className="text-muted-foreground">
          score {citation.score.toFixed(3)}
        </span>
      </div>
      <p className="text-foreground/90">{citation.text_preview}</p>
    </li>
  );
}
