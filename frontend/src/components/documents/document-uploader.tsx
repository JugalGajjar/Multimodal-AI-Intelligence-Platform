"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { uploadDocument } from "@/lib/documents-api";
import { useAuthStore } from "@/store/auth";

export function DocumentUploader() {
  const token = useAuthStore((s) => s.token);
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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

  return (
    <Card className="w-full max-w-2xl">
      <CardHeader>
        <CardTitle>Upload a document</CardTitle>
        <CardDescription>
          PDF, image, audio, or text. 50 MB max.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="file">File</Label>
          <Input
            ref={inputRef}
            id="file"
            type="file"
            accept="application/pdf,image/png,image/jpeg,image/webp,audio/mpeg,audio/mp3,audio/wav,text/plain,text/markdown"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button onClick={onUpload} disabled={!file || submitting}>
          {submitting ? "Uploading…" : "Upload"}
        </Button>
      </CardContent>
    </Card>
  );
}
