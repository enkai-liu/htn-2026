// Shape of GET /api/investigation/slop-index (and of public/slop-index.sample.json, the labelled fallback).
import { API_BASE, fetchJson } from "./api";
import type { SubclassKey } from "./chartTheme";

export interface SlopYear {
  year: number;
  scanned: number;
  ai_high: number;
  mixed_high: number;
  by_subclass: Partial<Record<SubclassKey, number>>;
  /** Wilson 95% interval on (ai_high + mixed_high) / scanned, as fractions */
  ci_low: number;
  ci_high: number;
}

export interface SlopTieIn {
  cliffs_delta: number;
  p_value: number;
  median_nn_sim_flagged: number;
  median_nn_sim_human: number;
  n_flagged?: number;
  n_human?: number;
  test?: string;
}

export interface SlopIndex {
  sample?: boolean;
  notice?: string;
  corpus?: string;
  detector?: string;
  years: SlopYear[];
  placebo_fpr: number | { rate: number } | null;
  placebo?: { years?: number[]; flagged?: number; scanned?: number; ci_low?: number; ci_high?: number };
  tie_in: SlopTieIn | null;
  user_percentile?: number | null;
}

export interface SlopResult { data: SlopIndex; isSample: boolean; reason: string | null }

function valid(d: unknown): d is SlopIndex {
  return !!d && typeof d === "object" && Array.isArray((d as SlopIndex).years) && (d as SlopIndex).years.length > 0;
}

/** Live results if the backend has them; otherwise the clearly-labelled sample file. */
export async function loadSlopIndex(): Promise<SlopResult> {
  let reason: string;
  try {
    const live = await fetchJson<unknown>(`${API_BASE}/api/investigation/slop-index`, 3500);
    if (valid(live)) return { data: live, isSample: !!live.sample, reason: null };
    reason = "the backend answered, but without per-year results";
  } catch {
    reason = "the investigation endpoint is not reachable";
  }
  const sample = await fetchJson<SlopIndex>("/slop-index.sample.json", 6000);
  return { data: sample, isSample: true, reason };
}

export const placeboRate = (d: SlopIndex): number | null =>
  typeof d.placebo_fpr === "number" ? d.placebo_fpr : d.placebo_fpr && typeof d.placebo_fpr.rate === "number" ? d.placebo_fpr.rate : null;
