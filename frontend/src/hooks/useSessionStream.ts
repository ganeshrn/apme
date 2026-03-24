/**
 * WebSocket hook for the FixSession lifecycle.
 *
 * Manages the full scan+fix flow over a single WS connection:
 *   connect → upload files → progress → tier1 results →
 *   AI proposals → approval → final result
 */

import { useCallback, useRef, useState } from "react";

// ── Types ──────────────────────────────────────────────────────────

export interface ProgressEntry {
  phase: string;
  message: string;
  level: number;
  timestamp: number;
}

export interface Patch {
  file: string;
  diff: string;
  applied_rules: string[];
  patched?: string;
}

export interface Tier1Result {
  idempotency_ok: boolean;
  patches: Patch[];
  format_diffs: Array<{ file: string; diff: string }>;
  report: Record<string, unknown> | null;
}

export interface Proposal {
  id: string;
  file: string;
  rule_id: string;
  line_start: number;
  line_end: number;
  before_text: string;
  after_text: string;
  diff_hunk: string;
  confidence: number;
  explanation: string;
  tier: number;
}

export interface RemainingViolation {
  rule_id: string;
  level: string;
  message: string;
  file: string;
}

export interface SessionResult {
  scan_id: string;
  patches: Patch[];
  report: Record<string, unknown> | null;
  remaining_violations: RemainingViolation[];
}

export type SessionStatus =
  | "idle"
  | "connecting"
  | "uploading"
  | "scanning"
  | "tier1_done"
  | "awaiting_approval"
  | "applying"
  | "complete"
  | "error";

export interface SessionOptions {
  ansibleVersion?: string;
  collections?: string[];
  enableAi?: boolean;
  aiModel?: string;
}

// ── Helpers ────────────────────────────────────────────────────────

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = reader.result as string;
      const idx = url.indexOf(",");
      resolve(idx >= 0 ? url.slice(idx + 1) : url);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function wsUrl(path: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}

// ── Hook ───────────────────────────────────────────────────────────

export function useSessionStream() {
  const [status, setStatus] = useState<SessionStatus>("idle");
  const [progress, setProgress] = useState<ProgressEntry[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [scanId, setScanId] = useState<string | null>(null);
  const [tier1, setTier1] = useState<Tier1Result | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [result, setResult] = useState<SessionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const statusRef = useRef<SessionStatus>("idle");

  const updateStatus = useCallback((s: SessionStatus) => {
    statusRef.current = s;
    setStatus(s);
  }, []);

  const reset = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    updateStatus("idle");
    setProgress([]);
    setSessionId(null);
    setScanId(null);
    setTier1(null);
    setProposals([]);
    setResult(null);
    setError(null);
  }, [updateStatus]);

  const startSession = useCallback(
    async (files: File[], options: SessionOptions = {}) => {
      reset();
      updateStatus("connecting");

      const ws = new WebSocket(wsUrl("/api/v1/ws/session"));
      wsRef.current = ws;

      ws.onopen = async () => {
        updateStatus("uploading");

        const startOptions: Record<string, unknown> = {
          ansible_version: options.ansibleVersion || "",
          collections: options.collections || [],
          enable_ai: options.enableAi ?? true,
        };
        if (options.aiModel) {
          startOptions.ai_model = options.aiModel;
        }
        ws.send(JSON.stringify({ type: "start", options: startOptions }));

        for (const file of files) {
          const content = await fileToBase64(file);
          const path =
            (file as File & { webkitRelativePath?: string })
              .webkitRelativePath || file.name;
          ws.send(JSON.stringify({ type: "file", path, content }));
        }

        ws.send(JSON.stringify({ type: "files_done" }));
      };

      ws.onmessage = (event) => {
        let msg: Record<string, unknown>;
        try {
          msg = JSON.parse(event.data as string);
        } catch {
          return;
        }

        switch (msg.type) {
          case "session_created":
            setSessionId(msg.session_id as string);
            setScanId(msg.scan_id as string);
            updateStatus("scanning");
            break;

          case "progress":
            setProgress((prev) => [
              ...prev,
              {
                phase: (msg.phase as string) || "",
                message: (msg.message as string) || "",
                level: (msg.level as number) ?? 2,
                timestamp: Date.now(),
              },
            ]);
            break;

          case "tier1_complete":
            setTier1(msg as unknown as Tier1Result);
            updateStatus("tier1_done");
            break;

          case "proposals":
            setProposals(msg.proposals as Proposal[]);
            updateStatus("awaiting_approval");
            break;

          case "approval_ack":
            if (msg.status === "COMPLETE") {
              updateStatus("applying");
            }
            break;

          case "result":
            setResult(msg as unknown as SessionResult);
            updateStatus("complete");
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ type: "close" }));
              setTimeout(() => {
                if (
                  ws.readyState === WebSocket.OPEN ||
                  ws.readyState === WebSocket.CLOSING
                ) {
                  ws.close(1000);
                }
              }, 100);
            }
            break;

          case "expiring":
            // TTL warning — could surface in UI later
            break;

          case "error":
            setError((msg.message as string) || "Unknown error");
            updateStatus("error");
            break;

          case "closed":
            if (
              statusRef.current !== "complete" &&
              statusRef.current !== "error"
            ) {
              updateStatus("complete");
            }
            break;
        }
      };

      ws.onerror = () => {
        setError("WebSocket connection error");
        updateStatus("error");
      };

      ws.onclose = (event) => {
        if (
          event.code !== 1000 &&
          statusRef.current !== "complete" &&
          statusRef.current !== "error"
        ) {
          setError("Connection closed unexpectedly");
          updateStatus("error");
        }
      };
    },
    [reset, updateStatus],
  );

  const approve = useCallback((approvedIds: string[]) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "approve", approved_ids: approvedIds }));
    }
  }, []);

  const extend = useCallback(() => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "extend" }));
    }
  }, []);

  const closeSession = useCallback(() => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "close" }));
    }
  }, []);

  const cancel = useCallback(() => {
    wsRef.current?.close();
    updateStatus("idle");
  }, [updateStatus]);

  return {
    status,
    progress,
    sessionId,
    scanId,
    tier1,
    proposals,
    result,
    error,
    startSession,
    approve,
    extend,
    closeSession,
    cancel,
    reset,
  };
}
