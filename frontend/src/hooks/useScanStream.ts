import { useCallback, useRef, useState } from "react";

export interface ProgressEntry {
  phase: string;
  message: string;
  level: number;
  timestamp: number;
}

export interface ScanResult {
  scan_id: string;
  total_violations: number;
  session_id: string;
}

export type ScanStatus = "idle" | "uploading" | "scanning" | "done" | "error";

interface ScanOptions {
  ansibleVersion?: string;
  collections?: string;
}

export function useScanStream() {
  const [status, setStatus] = useState<ScanStatus>("idle");
  const [progress, setProgress] = useState<ProgressEntry[]>([]);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    setStatus("idle");
    setProgress([]);
    setResult(null);
    setError(null);
  }, []);

  const startScan = useCallback(
    async (files: File[], options: ScanOptions = {}) => {
      reset();
      setStatus("uploading");

      const controller = new AbortController();
      abortRef.current = controller;

      const form = new FormData();
      for (const f of files) {
        const relativePath =
          (f as File & { webkitRelativePath?: string }).webkitRelativePath ||
          f.name;
        form.append("files", f, relativePath);
      }
      if (options.ansibleVersion) {
        form.append("ansible_version", options.ansibleVersion);
      }
      if (options.collections) {
        form.append("collections", options.collections);
      }

      try {
        const resp = await fetch("/api/v1/scans", {
          method: "POST",
          body: form,
          signal: controller.signal,
        });

        if (!resp.ok) {
          const text = await resp.text();
          setError(`Upload failed: ${resp.status} ${text}`);
          setStatus("error");
          return;
        }

        setStatus("scanning");

        const reader = resp.body?.getReader();
        if (!reader) {
          setError("No response stream available");
          setStatus("error");
          return;
        }

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          const blocks = buffer.split("\n\n");
          buffer = blocks.pop() || "";

          for (const block of blocks) {
            if (!block.trim()) continue;
            const lines = block.split("\n");
            let eventType = "";
            let data = "";
            for (const line of lines) {
              if (line.startsWith("event: ")) eventType = line.slice(7);
              else if (line.startsWith("data: ")) data = line.slice(6);
            }
            if (!eventType || !data) continue;

            try {
              const parsed = JSON.parse(data);
              if (eventType === "progress") {
                setProgress((prev) => [
                  ...prev,
                  {
                    phase: parsed.phase || "",
                    message: parsed.message || "",
                    level: parsed.level ?? 2,
                    timestamp: Date.now(),
                  },
                ]);
              } else if (eventType === "result") {
                setResult(parsed);
                setStatus("done");
              } else if (eventType === "error") {
                setError(parsed.message || "Unknown error");
                setStatus("error");
              }
            } catch {
              // skip malformed JSON
            }
          }
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setError((err as Error).message || "Network error");
          setStatus("error");
        }
      }
    },
    [reset],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setStatus("idle");
  }, []);

  return { status, progress, result, error, startScan, cancel, reset };
}
