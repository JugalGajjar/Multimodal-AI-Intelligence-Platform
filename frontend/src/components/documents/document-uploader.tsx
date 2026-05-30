"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CloudUpload, Loader2, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";

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

export function DocumentUploader() {
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
    try {
      await uploadDocument(token, file);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
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

  return (
    <Card className="glass w-full" data-testid="document-uploader">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <UploadCloud className="size-4 text-[color:var(--brand)]" aria-hidden="true" />
          Upload a document
        </CardTitle>
        <CardDescription>
          PDF, image, audio, or text. 50 MB max.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <label
          htmlFor="file"
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          className={
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors " +
            (dragOver
              ? "border-[color:var(--brand)] bg-accent/40"
              : "border-border/70 hover:border-[color:var(--brand)] hover:bg-accent/30")
          }
        >
          <span
            aria-hidden="true"
            className="grid size-10 place-items-center rounded-lg bg-gradient-brand text-brand-foreground glow-brand"
          >
            <CloudUpload className="size-5" />
          </span>
          {file ? (
            <span className="text-sm">
              <span className="font-medium">{file.name}</span>{" "}
              <span className="text-muted-foreground">
                ({(file.size / 1024).toFixed(1)} KB)
              </span>
            </span>
          ) : (
            <>
              <span className="text-sm font-medium">
                Drop a file or click to choose
              </span>
              <span className="text-xs text-muted-foreground">
                PDF · PNG · JPG · WebP · MP3 · WAV · TXT · MD
              </span>
            </>
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

        <div className="flex justify-end">
          <Button
            onClick={onUpload}
            disabled={!file || submitting}
            className="bg-gradient-brand text-brand-foreground glow-brand"
          >
            {submitting ? (
              <>
                <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                Uploading…
              </>
            ) : (
              <>Upload</>
            )}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
