import type {
  ActivityDetail,
  ActivitySummary,
  AiAcceptanceEntry,
  AiModelInfo,
  CreateProjectRequest,
  DashboardSummary,
  HealthStatus,
  PaginatedResponse,
  ProjectDetail,
  ProjectRanking,
  ProjectSummary,
  RemediationRateEntry,
  SessionDetail,
  SessionSummary,
  TopViolation,
  TrendPoint,
  UpdateProjectRequest,
  ViolationDetail,
} from "../types/api";

const BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { Accept: "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export function getHealth(): Promise<HealthStatus> {
  return request("/health");
}

export function listSessions(
  limit = 50,
  offset = 0,
): Promise<PaginatedResponse<SessionSummary>> {
  return request(`/sessions?limit=${limit}&offset=${offset}`);
}

export function listActivity(
  limit = 50,
  offset = 0,
  sessionId?: string,
): Promise<PaginatedResponse<ActivitySummary>> {
  let url = `/activity?limit=${limit}&offset=${offset}`;
  if (sessionId) url += `&session_id=${sessionId}`;
  return request(url);
}

export function getActivity(scanId: string): Promise<ActivityDetail> {
  return request(`/activity/${scanId}`);
}

export async function deleteActivity(scanId: string): Promise<void> {
  const res = await fetch(`${BASE}/activity/${scanId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status}`);
}

export function getSession(sessionId: string): Promise<SessionDetail> {
  return request(`/sessions/${sessionId}`);
}

export function getTopViolations(limit = 20): Promise<TopViolation[]> {
  return request(`/violations/top?limit=${limit}`);
}

export function getSessionTrend(sessionId: string): Promise<TrendPoint[]> {
  return request(`/sessions/${sessionId}/trend`);
}

export function getRemediationRates(limit = 20): Promise<RemediationRateEntry[]> {
  return request(`/stats/remediation-rates?limit=${limit}`);
}

export function getAiAcceptance(): Promise<AiAcceptanceEntry[]> {
  return request(`/stats/ai-acceptance`);
}

export function listAiModels(): Promise<AiModelInfo[]> {
  return request(`/ai/models`);
}

// ── Project API (ADR-037) ────────────────────────────────────────────

export function createProject(body: CreateProjectRequest): Promise<ProjectSummary> {
  return request("/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listProjects(
  limit = 50,
  offset = 0,
  sortBy = "created_at",
  order = "desc",
): Promise<PaginatedResponse<ProjectSummary>> {
  return request(`/projects?limit=${limit}&offset=${offset}&sort_by=${sortBy}&order=${order}`);
}

export function getProject(projectId: string): Promise<ProjectDetail> {
  return request(`/projects/${projectId}`);
}

export function updateProject(
  projectId: string,
  body: UpdateProjectRequest,
): Promise<ProjectSummary> {
  return request(`/projects/${projectId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteProject(projectId: string): Promise<void> {
  const res = await fetch(`${BASE}/projects/${projectId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`${res.status}`);
}

export function listProjectActivity(
  projectId: string,
  limit = 50,
  offset = 0,
): Promise<PaginatedResponse<ActivitySummary>> {
  return request(`/projects/${projectId}/activity?limit=${limit}&offset=${offset}`);
}

export function listProjectViolations(
  projectId: string,
  limit = 50,
  offset = 0,
  severity?: string,
  ruleId?: string,
): Promise<ViolationDetail[]> {
  let url = `/projects/${projectId}/violations?limit=${limit}&offset=${offset}`;
  if (severity) url += `&severity=${severity}`;
  if (ruleId) url += `&rule_id=${ruleId}`;
  return request(url);
}

export function getProjectTrend(
  projectId: string,
  limit = 20,
): Promise<TrendPoint[]> {
  return request(`/projects/${projectId}/trend?limit=${limit}`);
}

export function getDashboardSummary(): Promise<DashboardSummary> {
  return request("/dashboard/summary");
}

export function getDashboardRankings(
  sortBy = "health_score",
  order = "desc",
  limit = 10,
): Promise<ProjectRanking[]> {
  return request(`/dashboard/rankings?sort_by=${sortBy}&order=${order}&limit=${limit}`);
}

// ── Feedback (POC) ─────────────────────────────────────────────────────

export function getFeedbackEnabled(): Promise<{ enabled: boolean }> {
  return request("/feedback/enabled");
}
