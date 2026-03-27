/**
 * Common types for check/remediate operations shared by both the Playground
 * (useSessionStream) and Project (useProjectOperation) hooks.
 */

export type OperationStatus =
  | "idle"
  | "connecting"
  | "preparing"
  | "cloning"
  | "checking"
  | "tier1_done"
  | "awaiting_approval"
  | "applying"
  | "complete"
  | "disconnected"
  | "error";

export interface OperationProgress {
  phase: string;
  message: string;
  timestamp: number;
  progress?: number;
  level?: number;
}

export interface OperationProposal {
  id: string;
  rule_id: string;
  file: string;
  tier: number;
  confidence: number;
  explanation?: string;
  diff_hunk?: string;
  status?: 'proposed' | 'declined';
  suggestion?: string;
  line_start?: number;
}

export interface OperationResult {
  total_violations: number;
  fixable: number;
  ai_candidate: number;
  ai_proposed: number;
  ai_declined: number;
  ai_accepted: number;
  manual_review: number;
  remediated_count?: number;
}

export interface OperationState {
  status: OperationStatus;
  progress: OperationProgress[];
  proposals: OperationProposal[];
  result: OperationResult | null;
  error: string | null;
  approve: (ids: string[]) => void;
  cancel: () => void;
  reset: () => void;
}
