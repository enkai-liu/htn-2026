// Thin client for the FastAPI backend (docs/events.md, "Transport").

/** Inlined at build time. Empty string is allowed and means "same origin" (a reverse-proxied deploy). */
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(message: string, public readonly status: number | null) {
    super(message);
    this.name = "ApiError";
  }
}

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  } catch {
    /* not JSON */
  }
  return `HTTP ${res.status}`;
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = 15000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, signal: ctrl.signal, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  } catch (err) {
    const aborted = err instanceof DOMException && err.name === "AbortError";
    throw new ApiError(aborted ? "The backend did not answer in time." : "Could not reach the backend.", null);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) throw new ApiError(await readError(res), res.status);
  return (await res.json()) as T;
}

export function createRun(ideaText: string, url?: string): Promise<{ run_id: string }> {
  const body: { idea_text: string; url?: string } = { idea_text: ideaText };
  if (url) body.url = url;
  return request("/api/runs", { method: "POST", body: JSON.stringify(body) });
}

export type ActionName = "arm_watch" | "draft_pitch" | "writeback";

export function runAction(runId: string, action: string, body?: Record<string, unknown>): Promise<{ ok: boolean; [k: string]: unknown }> {
  return request(`/api/runs/${encodeURIComponent(runId)}/actions/${encodeURIComponent(action)}`, { method: "POST", body: JSON.stringify(body ?? {}) }, 70000);
}

/** One turn of the coaching conversation; the reply arrives on the event stream. */
export function coachSay(runId: string, text: string, mid?: string | null): Promise<{ ok: boolean; [k: string]: unknown }> {
  return request(`/api/runs/${encodeURIComponent(runId)}/coach`, { method: "POST", body: JSON.stringify({ text, ...(mid ? { mid } : {}) }) }, 100000);
}

export function rescoreMutation(runId: string, mid: string): Promise<{ ok: boolean; [k: string]: unknown }> {
  return request(`/api/runs/${encodeURIComponent(runId)}/mutations/${encodeURIComponent(mid)}/rescore`, { method: "POST" }, 70000);
}

export async function fetchJson<T>(url: string, timeoutMs = 6000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    if (!res.ok) throw new ApiError(`HTTP ${res.status}`, res.status);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}
