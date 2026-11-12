import type {
  AuditEvent,
  BatchResult,
  Catalog,
  Device,
  DryRun,
  Me,
  Onboarding,
  OnboardingDetail,
  Page,
  Preview,
  Stats,
  Template,
} from "./types";

const TOKEN_KEY = "hatch.token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `request failed (${status})`);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    setToken(null);
    window.dispatchEvent(new Event("hatch:logout"));
  }
  const text = await response.text();
  const data = text && response.headers.get("content-type")?.includes("json") ? JSON.parse(text) : text;
  if (!response.ok) throw new ApiError(response.status, (data as { detail?: unknown })?.detail ?? data);
  return data as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  me: () => request<Me>("/api/v1/me"),
  stats: () => request<Stats>("/api/v1/stats"),
  catalog: () => request<Catalog>("/api/v1/catalog"),
  suggest: (site: string, role: string, count = 1) =>
    request<{ hostname: string; mgmt_ip: string }[]>(
      `/api/v1/catalog/suggest?site=${encodeURIComponent(site)}&role=${encodeURIComponent(role)}&count=${count}`,
    ),
  list: (params: Record<string, string>) =>
    request<Page<Onboarding>>(`/api/v1/onboardings?${new URLSearchParams(params)}`),
  get: (id: string) => request<OnboardingDetail>(`/api/v1/onboardings/${id}`),
  preview: (id: string) => request<Preview>(`/api/v1/onboardings/${id}/preview`),
  dryRun: (body: unknown) => post<DryRun>("/api/v1/onboardings/dry-run", body),
  create: (body: unknown) => post<BatchResult>("/api/v1/onboardings", body),
  importCsv: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<BatchResult>("/api/v1/onboardings/import", { method: "POST", body: form });
  },
  action: (id: string, action: string, body?: unknown) =>
    post<{ onboarding: Onboarding; message: string }>(`/api/v1/onboardings/${id}/${action}`, body ?? {}),
  report: (id: string) => request<string>(`/api/v1/onboardings/${id}/report`),
  templates: () => request<Template[]>("/api/v1/templates"),
  template: (key: string) =>
    request<Template & { source: string; day0_source: string | null; example: unknown }>(
      `/api/v1/templates/${key}`,
    ),
  devices: () => request<Device[]>("/api/v1/devices"),
  audit: (params: Record<string, string> = {}) =>
    request<AuditEvent[]>(`/api/v1/audit?${new URLSearchParams(params)}`),
};

export function eventsUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/api/v1/events?token=${encodeURIComponent(getToken() ?? "")}`;
}

export function errorMessages(error: unknown): string[] {
  if (error instanceof ApiError) {
    const detail = error.detail as { errors?: { field: string; message: string }[] } | string;
    if (typeof detail === "object" && detail?.errors) return detail.errors.map((e) => `${e.field}: ${e.message}`);
    return [error.message];
  }
  return [String(error)];
}
