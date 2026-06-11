"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageSquareText, ShieldCheck, Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import {
  fetchChatSettings,
  updateChatSettings,
  type RagMode,
} from "@/lib/settings-api";
import { useAuthStore } from "@/store/auth";

const MODES: Array<{
  value: RagMode;
  label: string;
  description: string;
  Icon: typeof ShieldCheck;
}> = [
  {
    value: "strict",
    label: "Strict",
    description:
      "Only answer when grounded in your documents (or cited web sources). Low-confidence answers are withheld.",
    Icon: ShieldCheck,
  },
  {
    value: "regular",
    label: "Regular",
    description:
      "Blend your documents with the model's own knowledge. Citations appear when documents are used.",
    Icon: Sparkles,
  },
];

export function ChatSettingsCard() {
  const token = useAuthStore((s) => s.token);
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery({
    queryKey: ["chat-settings"],
    queryFn: () => fetchChatSettings(token!),
    enabled: !!token,
  });

  // Local slider position while dragging; null = mirror the server value.
  // PATCH fires on release only, then control returns to the query data.
  const [sliderValue, setSliderValue] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);

  async function patch(patchBody: Parameters<typeof updateChatSettings>[1]) {
    if (!token || saving) return;
    setSaving(true);
    try {
      await updateChatSettings(token, patchBody);
      await queryClient.invalidateQueries({ queryKey: ["chat-settings"] });
    } catch {
      toast.error("Could not save chat settings. Try again.");
    } finally {
      setSaving(false);
    }
  }

  async function commitSlider() {
    if (sliderValue !== null && data && sliderValue !== data.web_max_results) {
      await patch({ web_max_results: sliderValue });
    }
    setSliderValue(null);
  }

  return (
    <Card className="glass" data-testid="chat-settings-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageSquareText className="size-4" aria-hidden="true" />
          Chat
        </CardTitle>
        <CardDescription>
          How answers are grounded and how much web context is pulled in when
          the Web toggle is on.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {isLoading && (
          <div className="space-y-3" data-testid="chat-settings-skeleton">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-8 w-2/3" />
          </div>
        )}
        {isError && (
          <p className="text-sm text-destructive">
            Could not load chat settings.
          </p>
        )}
        {data && (
          <>
            <fieldset className="space-y-2">
              <legend className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                RAG mode
              </legend>
              <div className="grid gap-2 sm:grid-cols-2">
                {MODES.map(({ value, label, description, Icon }) => {
                  const active = data.rag_mode === value;
                  return (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={active}
                      disabled={saving}
                      onClick={() => !active && patch({ rag_mode: value })}
                      data-testid={`rag-mode-${value}`}
                      className={cn(
                        "rounded-xl border px-4 py-3 text-left transition-colors",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--brand)]/40",
                        "disabled:pointer-events-none disabled:opacity-60",
                        active
                          ? "border-[color:var(--brand)]/60 bg-[color:var(--brand)]/5"
                          : "border-border/60 bg-background/40 hover:bg-background/70",
                      )}
                    >
                      <span className="flex items-center gap-2 text-sm font-medium">
                        <Icon
                          className={cn(
                            "size-3.5",
                            active && "text-[color:var(--brand)]",
                          )}
                          aria-hidden="true"
                        />
                        {label}
                        {active && (
                          <span className="ml-auto text-[10px] font-medium uppercase tracking-wide text-[color:var(--brand)]">
                            active
                          </span>
                        )}
                      </span>
                      <span className="mt-1 block text-xs leading-relaxed text-muted-foreground">
                        {description}
                      </span>
                    </button>
                  );
                })}
              </div>
            </fieldset>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label
                  htmlFor="web-max-results"
                  className="text-xs font-medium uppercase tracking-wider text-muted-foreground"
                >
                  Max websites for web search
                </label>
                <span
                  className="font-mono text-sm text-foreground"
                  data-testid="web-max-results-value"
                >
                  {sliderValue ?? data.web_max_results}
                </span>
              </div>
              <input
                id="web-max-results"
                type="range"
                min={1}
                max={10}
                step={1}
                value={sliderValue ?? data.web_max_results}
                disabled={saving}
                onChange={(e) => setSliderValue(Number(e.target.value))}
                onPointerUp={commitSlider}
                onKeyUp={commitSlider}
                onBlur={commitSlider}
                className="w-full accent-[color:var(--brand)]"
              />
              <p className="text-xs text-muted-foreground">
                How many search results are fetched and cited when the Web
                toggle is on. More sites = richer context, slower answers.
              </p>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
