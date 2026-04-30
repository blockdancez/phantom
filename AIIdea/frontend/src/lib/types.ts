export interface SourceItem {
  id: string;
  source: string;
  title: string;
  url: string;
  content: string;
  raw_data: Record<string, unknown>;
  category: string | null;
  tags: string[] | null;
  score: number | null;
  summary_zh: string | null;
  problem: string | null;
  opportunity: string | null;
  target_user: string | null;
  why_now: string | null;
  collected_at: string;
  processed: boolean;
  created_at: string;
  // Joined by the API when an AnalysisResult has source_item_id = this item.
  analysis_result_id: string | null;
}

export interface SourceItemList {
  items: SourceItem[];
  total: number;
  page: number;
  per_page: number;
}

export interface AnalysisResult {
  id: string;
  idea_title: string;
  overall_score: number;
  project_name: string | null;
  product_type: string | null;
  aijuicer_workflow_id: string | null;
  product_idea: string | null;
  target_audience: string | null;
  use_case: string | null;
  pain_points: string | null;
  key_features: string | null;
  source_quote: string | null;
  user_story: string | null;
  source_item_id: string | null;
  reasoning: string | null;
  // Joined from the anchor SourceItem by the API
  source_item_title: string | null;
  source_item_url: string | null;
  source_item_ids: string[];
  agent_trace: Record<string, unknown> | null;
  created_at: string;
}

export interface AnalysisResultList {
  items: AnalysisResult[];
  total: number;
  page: number;
  per_page: number;
}

export interface SourceStat {
  source: string;
  count: number;
  last_collected_at: string | null;
  unprocessed: number;
}

export interface SourceStatsList {
  items: SourceStat[];
  total_sources: number;
  total_items: number;
}

export interface ScheduledJob {
  id: string;
  name: string;
  next_run_time: string | null;
  trigger: string;
}

export interface HealthStatus {
  status: "ok" | "fail";
  db: "ok" | "fail";
  scheduler: "ok" | "fail";
}

export interface PipelineStatus {
  total_items: number;
  processed_items: number;
  unprocessed_items: number;
  last_collected_at: string | null;
  analysis_count: number;
  last_analysis_at: string | null;
  distinct_sources: number;
  jobs: ScheduledJob[];
}


export interface ProductExperienceReportListItem {
  id: string;
  product_slug: string;
  product_name: string;
  product_url: string;
  project_name: string | null;
  aijuicer_workflow_id: string | null;
  run_completed_at: string | null;
  status: "completed" | "partial" | "failed" | "running";
  login_used: "google" | "none" | "failed" | "skipped";
  overall_ux_score: number | null;
  product_thesis: string | null;
  summary_zh: string | null;
  screenshots_count: number;
}

export interface CoreFeature {
  name: string;
  priority: "must" | "should" | "nice" | string | null;
  where_seen: string | null;
  rationale: string | null;
}

export interface TargetUserProfile {
  persona: string | null;
  scenarios: string[];
  pain_points: string[];
  why_this_product: string | null;
}

export interface DifferentiationOpportunity {
  observation: string;
  opportunity: string | null;
  why_it_matters: string | null;
}

export interface InnovationAngle {
  angle: string;
  hypothesis: string | null;
  examples: string[];
}

export interface FeatureInventoryItem {
  name: string;
  where_found: string;
  notes: string;
}

export interface ScreenshotEntry {
  name: string;
  path: string;
  taken_at: string;
}

export interface ProductExperienceReport {
  id: string;
  product_slug: string;
  product_url: string;
  product_name: string;
  project_name: string | null;
  aijuicer_workflow_id: string | null;
  run_started_at: string;
  run_completed_at: string | null;
  status: "completed" | "partial" | "failed" | "running";
  failure_reason: string | null;
  login_used: "google" | "none" | "failed" | "skipped";
  overall_ux_score: number | null;
  // 借鉴启发字段（新版）
  product_thesis: string | null;
  core_features: CoreFeature[] | null;
  target_user_profile: TargetUserProfile | null;
  differentiation_opportunities: DifferentiationOpportunity[] | null;
  innovation_angles: InnovationAngle[] | null;
  // 兼容旧字段
  summary_zh: string | null;
  feature_inventory: FeatureInventoryItem[] | null;
  strengths: string | null;
  weaknesses: string | null;
  monetization_model: string | null;
  target_user: string | null;
  screenshots: ScreenshotEntry[] | null;
  agent_trace: Record<string, unknown> | null;
  created_at: string;
}

export interface ProductExperienceListResponse {
  items: ProductExperienceReportListItem[];
  total: number;
  page: number;
  per_page: number;
}
