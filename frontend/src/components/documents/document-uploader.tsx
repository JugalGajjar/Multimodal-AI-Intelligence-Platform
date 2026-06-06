"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CloudUpload, Loader2, UploadCloud, X } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { uploadDocument } from "@/lib/documents-api";
import { useAuthStore } from "@/store/auth";

const ACCEPTED =
  "application/pdf,image/png,image/jpeg,image/webp,audio/mpeg,audio/mp3,audio/wav,text/plain,text/markdown";

export function DocumentUploader({
  compact = false,
}: {
  /** When true, renders a slim single-row uploader suitable for placing
   *  alongside other components without dominating the viewport. */
  compact?: boolean;
}) {
  const token = useAuthStore((s) => s.token);
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  async function onUpload() {
    if (!file || !token) return;
    setError(null);
    setSubmitting(true);
    const uploadedName = file.name;
    try {
      await uploadDocument(token, file);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
      toast.success(uploadedName, {
        description: "Uploaded successfully.",
        duration: 5000,
      });
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
    } catch (err) {
      if (err instanceof ApiError && err.status === 415) {
        setError("Unsupported file type.");
      } else if (err instanceof ApiError && err.status === 413) {
        setError("File is too large (50 MB max).");
      } else if (err instanceof ApiError && err.status === 400) {
        setError("File is empty.");
      } else {
        setError("Upload failed. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  function handleFileSelect(f: File | null | undefined) {
    if (f) setFile(f);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    handleFileSelect(e.dataTransfer.files?.[0]);
  }

  // Slim, single-row variant: dropzone left, file info + button right.
  if (compact) {
    return (
      <Card
        className="glass w-full px-4 py-3"
        data-testid="document-uploader"
      >
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
          <label
            htmlFor="file"
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            className={
              "flex flex-1 cursor-pointer items-center gap-3 rounded-lg border border-dashed px-4 py-2.5 transition-colors " +
              (dragOver
                ? "border-[color:var(--brand)] bg-accent/40"
                : "border-border/70 hover:border-[color:var(--brand)] hover:bg-accent/30")
            }
          >
            <span
              aria-hidden="true"
              className="grid size-8 shrink-0 place-items-center rounded-md bg-gradient-brand text-brand-foreground glow-brand"
            >
              <CloudUpload className="size-4" />
            </span>
            {file ? (
              <span className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                <span className="truncate font-medium">{file.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  ({(file.size / 1024).toFixed(1)} KB)
                </span>
                <button
                  type="button"
                  onClick={(e) => {
                    e.preventDefault();
                    setFile(null);
                    if (inputRef.current) inputRef.current.value = "";
                  }}
                  aria-label="Clear selected file"
                  className="ml-auto shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
                >
                  <X className="size-3.5" />
                </button>
              </span>
            ) : (
              <span className="min-w-0 flex-1 text-sm">
                <span className="font-medium">Drop a file or click</span>{" "}
                <span className="hidden text-xs text-muted-foreground sm:inline">
                  (PDF, image, audio, text. 50 MB max.)
                </span>
              </span>
            )}
            <input
              ref={inputRef}
              id="file"
              type="file"
              accept={ACCEPTED}
              onChange={(e) => handleFileSelect(e.target.files?.[0])}
              className="sr-only"
              aria-label="File"
            />
          </label>
          <Button
            onClick={onUpload}
            disabled={!file || submitting}
            size="sm"
            className="w-full bg-gradient-brand text-brand-foreground glow-brand px-5 sm:w-auto"
          >
            {submitting ? (
              <>
                <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                Uploading
              </>
            ) : (
              "Upload"
            )}
          </Button>
        </div>
        {error && (
          <p role="alert" className="mt-2 text-sm text-destructive">
            {error}
          </p>
        )}
      </Card>
    );
  }

  // Full uploader (used on /dashboard/documents) — original layout.
  return (
    <Card className="glass w-full py-6" data-testid="document-uploader">
      <CardHeader className="px-4 pb-2 sm:px-6">
        <CardTitle className="flex items-center gap-2 text-base">
          <UploadCloud className="size-4 text-[color:var(--brand)]" aria-hidden="true" />
          Upload a document
        </CardTitle>
        <CardDescription className="mt-1">
          PDF, image, audio, or text. 50 MB max.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5 px-4 pt-2 sm:px-6">
        <label
          htmlFor="file"
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={
            "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed px-4 py-10 text-center transition-colors sm:px-6 sm:py-12 " +
            (dragOver
              ? "border-[color:var(--brand)] bg-accent/40"
              : "border-border/70 hover:border-[color:var(--brand)] hover:bg-accent/30")
          }
        >
          <span
            aria-hidden="true"
            className="grid size-11 place-items-center rounded-lg bg-gradient-brand text-brand-foreground glow-brand"
          >
            <CloudUpload className="size-5" />
          </span>
          {file ? (
            <span className="break-all text-sm">
              <span className="font-medium">{file.name}</span>{" "}
              <span className="text-muted-foreground">
                ({(file.size / 1024).toFixed(1)} KB)
              </span>
            </span>
          ) : (
            <div className="space-y-1">
              <p className="text-sm font-medium">
                Drop a file or click to choose
              </p>
              <p className="text-xs text-muted-foreground">
                PDF, PNG, JPG, WebP, MP3, WAV, TXT, MD
              </p>
            </div>
          )}
          <input
            ref={inputRef}
            id="file"
            type="file"
            accept={ACCEPTED}
            onChange={(e) => handleFileSelect(e.target.files?.[0])}
            className="sr-only"
            aria-label="File"
          />
        </label>

        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}

        <div className="flex justify-stretch pt-1 sm:justify-end">
          <Button
            onClick={onUpload}
            disabled={!file || submitting}
            className="w-full bg-gradient-brand text-brand-foreground glow-brand px-6 sm:w-auto"
          >
            {submitting ? (
              <>
                <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                Uploading
              </>
            ) : (
              "Upload"
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
