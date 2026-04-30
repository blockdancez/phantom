// Server Components run inside the dev server host and reach the backend via
// the internal API_URL; client components run in the browser and use the
// public NEXT_PUBLIC_API_URL. Defaults target the preallocated backend port
// (53839) so no env flag is strictly required during local development.
const DEFAULT_API_URL = "http://localhost:53839";

function getApiBase(): string {
  if (typeof window === "undefined" && process.env.API_URL) {
    return process.env.API_URL;
  }
  return process.env.NEXT_PUBLIC_API_URL || DEFAULT_API_URL;
}

export class ApiError extends Error {
  code: string;
  status: number;
  requestId: string | null;

  constructor(message: string, code: string, status: number, requestId: string | null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

interface Envelope<T> {
  code: string;
  message: string;
  data: T | null;
  request_id: string | null;
}

async function fetchAPI<T>(
  path: string,
  params?: Record<string, string>,
  init?: RequestInit,
): Promise<T> {
  const base = getApiBase();
  const url = new URL(`${base}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  }
  const res = await fetch(url.toString(), {
    ...init,
    next: init?.method ? undefined : { revalidate: 60 },
  });

  let body: Envelope<T> | null = null;
  try {
    body = (await res.json()) as Envelope<T>;
  } catch {
    throw new ApiError(`API error: ${res.status}`, "999999", res.status, null);
  }

  if (!body || typeof body !== "object" || !("code" in body)) {
    throw new ApiError(`Malformed API response`, "999999", res.status, null);
  }

  if (!res.ok || body.code !== "000000") {
    throw new ApiError(
      body.message || `API error: ${res.status}`,
      body.code || "999999",
      res.status,
      body.request_id,
    );
  }

  return body.data as T;
}

import type {
  SourceItem,
  SourceItemList,
  AnalysisResultList,
  AnalysisResult,
  SourceStatsList,
  PipelineStatus,
  HealthStatus,
} from "./types";

export interface SourceItemsQuery {
  page?: number;
  per_page?: number;
  source?: string;
  category?: string;
  min_score?: number;
  processed?: boolean;
  q?: string;
  sort?: "collected_at" | "score" | "title";
  order?: "asc" | "desc";
  collected_since?: string;
  collected_until?: string;
}

export async function getSourceItems(params?: SourceItemsQuery): Promise<SourceItemList> {
  const queryParams: Record<string, string> = {};
  if (params?.page) queryParams.page = String(params.page);
  if (params?.per_page) queryParams.per_page = String(params.per_page);
  if (params?.source) queryParams.source = params.source;
  if (params?.category) queryParams.category = params.category;
  if (params?.min_score != null) queryParams.min_score = String(params.min_score);
  if (params?.processed != null) queryParams.processed = String(params.processed);
  if (params?.q) queryParams.q = params.q;
  if (params?.sort) queryParams.sort = params.sort;
  if (params?.order) queryParams.order = params.order;
  if (params?.collected_since) queryParams.collected_since = params.collected_since;
  if (params?.collected_until) queryParams.collected_until = params.collected_until;
  return fetchAPI<SourceItemList>("/api/source-items", queryParams);
}

export async function getSourceItem(id: string): Promise<SourceItem> {
  return fetchAPI<SourceItem>(`/api/source-items/${id}`);
}

export async function getSourceStats(): Promise<SourceStatsList> {
  return fetchAPI<SourceStatsList>("/api/stats/sources");
}

export async function getHealth(): Promise<HealthStatus> {
  return fetchAPI<HealthStatus>("/api/health");
}

export async function getPipelineStatus(): Promise<PipelineStatus> {
  return fetchAPI<PipelineStatus>("/api/stats/pipeline");
}

export interface TriggerResponse {
  status: string;
  job_id: string;
  started_at: string;
  next_run_time: string | null;
  inserted: number | null;
  source: string | null;
}

export async function triggerJob(jobId: string): Promise<TriggerResponse> {
  return fetchAPI<TriggerResponse>(`/api/pipeline/trigger/${jobId}`, undefined, {
    method: "POST",
    cache: "no-store",
  });
}

export async function getAnalysisResults(params?: {
  page?: number;
  per_page?: number;
  min_score?: number;
  sort?: "created_at" | "score";
  order?: "asc" | "desc";
}): Promise<AnalysisResultList> {
  const queryParams: Record<string, string> = {};
  if (params?.page) queryParams.page = String(params.page);
  if (params?.per_page) queryParams.per_page = String(params.per_page);
  if (params?.min_score != null) queryParams.min_score = String(params.min_score);
  if (params?.sort) queryParams.sort = params.sort;
  if (params?.order) queryParams.order = params.order;
  return fetchAPI<AnalysisResultList>("/api/analysis-results", queryParams);
}

export async function getAnalysisResult(id: string): Promise<AnalysisResult> {
  return fetchAPI<AnalysisResult>(`/api/analysis-results/${id}`);
}

import type {
  ProductExperienceListResponse,
  ProductExperienceReport,
} from "./types";

export async function listProductExperienceReports(params: {
  page?: number;
  per_page?: number;
  product_slug?: string;
  q?: string;
  status?: "completed" | "partial" | "failed";
  min_score?: number;
  sort?: "started_at" | "completed_at" | "score";
  order?: "asc" | "desc";
}): Promise<ProductExperienceListResponse> {
  const queryParams: Record<string, string> = {};
  if (params.page) queryParams.page = String(params.page);
  if (params.per_page) queryParams.per_page = String(params.per_page);
  if (params.product_slug) queryParams.product_slug = params.product_slug;
  if (params.q) queryParams.q = params.q;
  if (params.status) queryParams.status = params.status;
  if (params.min_score != null) queryParams.min_score = String(params.min_score);
  if (params.sort) queryParams.sort = params.sort;
  if (params.order) queryParams.order = params.order;
  return fetchAPI<ProductExperienceListResponse>(
    "/api/product-experience-reports",
    queryParams,
  );
}

export async function getProductExperienceReport(
  id: string,
): Promise<ProductExperienceReport> {
  return fetchAPI<ProductExperienceReport>(
    `/api/product-experience-reports/${id}`,
  );
}

export interface TriggerExperienceUrlBody {
  url: string;
  name?: string;
  requires_login?: boolean;
}

export interface TriggerExperienceUrlResponse {
  report_id: string;
  status: string;
}

export async function triggerExperienceUrl(
  body: TriggerExperienceUrlBody,
): Promise<TriggerExperienceUrlResponse> {
  return fetchAPI<TriggerExperienceUrlResponse>(
    "/api/pipeline/experience-url",
    undefined,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    },
  );
}
