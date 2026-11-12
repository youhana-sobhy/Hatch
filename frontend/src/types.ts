export type Status =
  | "REGISTERED"
  | "VALIDATED"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "WAITING_FOR_DEVICE"
  | "DAY0_APPLIED"
  | "DAY1_CONFIGURING"
  | "VERIFYING"
  | "COMPLIANCE_CHECK"
  | "HANDING_OVER"
  | "COMPLETED"
  | "FAILED"
  | "ROLLED_BACK"
  | "CANCELLED";

export interface Onboarding {
  id: string;
  batch_id: string | null;
  hostname: string;
  serial: string;
  vendor: string;
  model: string;
  role: string;
  site: string;
  region: string;
  mode: "ztp" | "push";
  mgmt_ip: string;
  status: Status;
  failed_stage: string | null;
  error: string | null;
  attempt: number;
  template_key: string;
  template_version: string;
  rendered_sha256: string | null;
  requested_by: string;
  approved_by: string | null;
  requires_approval: boolean;
  ticket_ref: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface StageRun {
  stage: string;
  attempt: number;
  status: "running" | "succeeded" | "failed" | "skipped";
  started_at: string;
  finished_at: string | null;
  job_ref: string;
  output: string;
  details: Record<string, unknown>;
}

export interface ComplianceResult {
  rule_id: string;
  title: string;
  severity: "critical" | "high" | "medium" | "low";
  passed: boolean;
  evidence: string;
  attempt: number;
}

export interface OnboardingDetail extends Onboarding {
  attributes: Record<string, unknown>;
  stages: StageRun[];
  compliance: ComplianceResult[];
  allowed_actions: string[];
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Preview {
  template: string;
  template_version: string;
  layers: string[];
  config: string;
  diff: string;
  diff_against: string;
  secrets: string[];
  sha256: string;
}

export interface Issue {
  field: string;
  message: string;
}

export interface DryRun {
  valid: boolean;
  errors: Issue[];
  warnings: Issue[];
  vendor: string | null;
  requires_approval: boolean | null;
  preview: Preview | null;
}

export interface BatchResult {
  batch_id: string | null;
  created: Onboarding[];
  rejected: { index: number; hostname: string; errors: Issue[] }[];
}

export interface Catalog {
  sites: { name: string; region: string; mgmt_prefix: string; description: string }[];
  models: { name: string; vendor: string; roles: string[]; description: string }[];
  roles: string[];
  states: Status[];
}

export interface Template {
  key: string;
  vendor: string;
  role: string;
  version: string;
  full_version: string;
  status: string;
  owner: string;
  description: string;
  has_day0: boolean;
  required_vars: string[];
}

export interface AuditEvent {
  id: number;
  at: string;
  actor: string;
  action: string;
  onboarding_id: string | null;
  from_status: string | null;
  to_status: string | null;
  detail: Record<string, unknown>;
}

export interface Device {
  id: string;
  hostname: string;
  serial: string;
  mgmt_ip: string;
  vendor: string;
  model: string;
  role: string;
  site: string;
  region: string;
  status: string;
  monitored: boolean;
  onboarding_id: string | null;
}

export interface Stats {
  total: number;
  by_status: Record<string, number>;
  by_vendor: Record<string, number>;
  by_region: Record<string, number>;
  in_flight: number;
  completed: number;
  median_seconds_to_complete: number | null;
  first_time_right_rate: number | null;
  compliance_pass_rate: number | null;
  stage_failures_7d: Record<string, number>;
  active_devices: number;
}

export interface HatchEvent {
  type: string;
  at?: string;
  onboarding_id?: string;
  hostname?: string;
  from?: string;
  to?: string;
  stage?: string;
  status?: string;
  output?: string;
  actor?: string;
}

export interface Me {
  user: string;
  role: string;
  sites: string[];
}
