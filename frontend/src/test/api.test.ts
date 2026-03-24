import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

describe("api service", () => {
  beforeEach(() => {
    mockFetch.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function jsonResponse(data: unknown, status = 200) {
    return Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(data),
      text: () => Promise.resolve(JSON.stringify(data)),
    });
  }

  it("getHealth calls /api/v1/health", async () => {
    mockFetch.mockReturnValueOnce(jsonResponse({ status: "ok", database: "ok", components: [] }));
    const { getHealth } = await import("../services/api");
    const result = await getHealth();
    expect(result.status).toBe("ok");
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/health", expect.objectContaining({ headers: { Accept: "application/json" } }));
  });

  it("listScans calls /api/v1/scans with pagination", async () => {
    mockFetch.mockReturnValueOnce(jsonResponse({ total: 0, limit: 10, offset: 0, items: [] }));
    const { listScans } = await import("../services/api");
    await listScans(10, 5);
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/scans?limit=10&offset=5", expect.anything());
  });

  it("listScans appends session_id filter", async () => {
    mockFetch.mockReturnValueOnce(jsonResponse({ total: 0, limit: 10, offset: 0, items: [] }));
    const { listScans } = await import("../services/api");
    await listScans(10, 0, "abc123");
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/scans?limit=10&offset=0&session_id=abc123", expect.anything());
  });

  it("getScan calls correct path", async () => {
    mockFetch.mockReturnValueOnce(jsonResponse({ scan_id: "s1" }));
    const { getScan } = await import("../services/api");
    await getScan("s1");
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/scans/s1", expect.anything());
  });

  it("deleteScan calls DELETE", async () => {
    mockFetch.mockReturnValueOnce(Promise.resolve({ ok: true, status: 204 }));
    const { deleteScan } = await import("../services/api");
    await deleteScan("s1");
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/scans/s1", { method: "DELETE" });
  });

  it("deleteScan throws on failure", async () => {
    mockFetch.mockReturnValueOnce(Promise.resolve({ ok: false, status: 404 }));
    const { deleteScan } = await import("../services/api");
    await expect(deleteScan("s1")).rejects.toThrow("404");
  });

  it("getSession calls correct path", async () => {
    mockFetch.mockReturnValueOnce(jsonResponse({ session_id: "sess1", scans: [] }));
    const { getSession } = await import("../services/api");
    const result = await getSession("sess1");
    expect(result.session_id).toBe("sess1");
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/sessions/sess1", expect.anything());
  });

  it("getSessionTrend calls correct path", async () => {
    mockFetch.mockReturnValueOnce(jsonResponse([{ scan_id: "s1", total_violations: 10 }]));
    const { getSessionTrend } = await import("../services/api");
    const result = await getSessionTrend("sess1");
    expect(result).toHaveLength(1);
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/sessions/sess1/trend", expect.anything());
  });

  it("request throws on non-ok response", async () => {
    mockFetch.mockReturnValueOnce(jsonResponse("Not Found", 404));
    const { getHealth } = await import("../services/api");
    await expect(getHealth()).rejects.toThrow("404");
  });

  it("listAiModels calls /api/v1/ai/models", async () => {
    const models = [
      { id: "openai/gpt-4o", provider: "openai", name: "gpt-4o" },
      { id: "anthropic/claude-sonnet-4", provider: "anthropic", name: "claude-sonnet-4" },
    ];
    mockFetch.mockReturnValueOnce(jsonResponse(models));
    const { listAiModels } = await import("../services/api");
    const result = await listAiModels();
    expect(result).toHaveLength(2);
    expect(result[0]!.id).toBe("openai/gpt-4o");
    expect(result[1]!.provider).toBe("anthropic");
    expect(mockFetch).toHaveBeenCalledWith("/api/v1/ai/models", expect.objectContaining({ headers: { Accept: "application/json" } }));
  });

  it("listAiModels returns empty array on empty response", async () => {
    mockFetch.mockReturnValueOnce(jsonResponse([]));
    const { listAiModels } = await import("../services/api");
    const result = await listAiModels();
    expect(result).toHaveLength(0);
  });
});
