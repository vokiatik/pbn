import type { AICategory } from "../config/aiCategories";

export const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.PROD ? window.location.origin : "http://localhost:8080");

export function buildWebSocketUrl(publicId: string): string {
    const url = new URL(import.meta.env.VITE_WS_BASE || API_BASE || window.location.origin);
    url.protocol = url.protocol === "https:" || url.protocol === "wss:" ? "wss:" : "ws:";
    url.pathname = `${url.pathname.replace(/\/$/, "")}/ws`;
    url.search = new URLSearchParams({ project_id: publicId }).toString();
    return url.toString();
}

export type PipelineVersion = "ai";

export type CropRect = { x: number; y: number; width: number; height: number };

export type AISettings = {
    provider: "openai" | "gemini";
    category: AICategory;
    target_palette_size: number;
    preserve_elements: string[];
    simplify_elements: string[];
    prompt_guidance: string;
    page_size: "a3" | "a4";
    orientation: "portrait" | "landscape";
    fit_mode: "cover" | "contain";
    crop: CropRect | null;
};

export interface Project {
    id: string;
    public_id: string;
    user_id?: string;
    username: string;
    client_token?: string;
    original_filename: string;
    original_file_path: string;
    pipeline_version: PipelineVersion;
    ai_settings?: AISettings;
    ai_quality?: AIQuality;
    pbn_options?: PBNOption[];
    selected_pbn_difficulty?: PBNDifficulty;
    status: string;
    error_message?: string;
    created_at: string;
    updated_at: string;
    completed_at?: string;
    deleted_at?: string;
    files_count: number;
}

export type PBNDifficulty = "easy" | "medium" | "hard";

export interface PBNOption {
    difficulty: PBNDifficulty;
    status: "valid";
    region_count: number;
    palette_size: number;
    prefilled_detail_count: number;
    prefilled_area_percent: number;
    protected_boundary_retention: number;
    mean_reconstruction_delta_e_00: number;
    adaptive_label_count?: number;
    minimum_label_font_pt?: number;
    protected_mean_delta_e_00?: number;
    protected_p90_delta_e_00?: number;
    region_budget_overflow_percent?: number;
    advanced_area_percent?: number;
    selected_boundary_retention?: number;
    selected_prefilled_detail_count?: number;
    selected_forced_merge_count?: number;
    palette_protected_forced_merge_count?: number;
    protection_overflow_percent?: number;
}

export interface DetailProtectionMetadata {
    exists: boolean;
    width?: number;
    height?: number;
    coverage_percent?: number;
    sha256?: string;
    updated_at?: string;
    large_selection?: boolean;
}

export interface AIQuality {
    status: "pass" | "warn";
    codes: Array<"palette_mismatch" | "micro_detail_density" | "region_complexity" | string>;
    message: string;
    metrics: {
        mean_delta_e_00: number;
        p90_delta_e_00: number;
        estimated_region_count: number;
        micro_detail_area_percent: number;
    };
}

export interface ProjectFile {
    id: string;
    project_id: string;
    file_type: string;
    filename: string;
    file_path: string;
    mime_type: string;
    size_bytes: number;
    created_at: string;
}

export interface User {
    id: string;
    username: string;
    email: string;
    phone_number: string;
}

const clientTokenKey = "pbn_client_token";

export function getClientToken(): string {
    const existing = localStorage.getItem(clientTokenKey);
    if (existing) return existing;
    const created = crypto.randomUUID();
    localStorage.setItem(clientTokenKey, created);
    return created;
}

async function parseResponse<T>(res: Response): Promise<T> {
    if (!res.ok) {
        let message = "Request failed";
        try {
            const data = (await res.json()) as { error?: string };
            if (data.error) message = data.error;
        } catch {
            // ignore parse error
        }
        throw new Error(message);
    }
    return (await res.json()) as T;
}

export async function uploadProject(file: File): Promise<{ project_id: string; status: string; pipeline_version: PipelineVersion }> {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("pipeline_version", "ai");
    const res = await fetch(`${API_BASE}/api/projects`, {
        method: "POST",
        headers: { "X-Client-Token": getClientToken() },
        body: fd,
    });
    return parseResponse<{ project_id: string; status: string; pipeline_version: PipelineVersion }>(res);
}

export async function replaceProjectImage(
    publicId: string,
    file: File
): Promise<{ project_id: string; status: string; pipeline_version: PipelineVersion; files: ProjectFile[] }> {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/api/projects/${publicId}/image`, {
        method: "PUT",
        headers: { "X-Client-Token": getClientToken() },
        body: fd,
    });
    return parseResponse<{ project_id: string; status: string; pipeline_version: PipelineVersion; files: ProjectFile[] }>(res);
}

export async function listProjects(page: number, pageSize = 10): Promise<{ items: Project[]; total: number; total_pages: number }> {
    const res = await fetch(`${API_BASE}/api/projects?page=${page}&page_size=${pageSize}`);
    return parseResponse<{ items: Project[]; total: number; total_pages: number }>(res);
}

export async function getProject(publicId: string): Promise<{ project: Project; files: ProjectFile[] }> {
    const res = await fetch(`${API_BASE}/api/projects/${publicId}`);
    return parseResponse<{ project: Project; files: ProjectFile[] }>(res);
}

export async function deleteProject(publicId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/projects/${publicId}`, { method: "DELETE" });
    await parseResponse<{ status: string }>(res);
}

export async function runAIPipeline(
    publicId: string,
    settings: AISettings
): Promise<{ project_id: string; status: string }> {
    const res = await fetch(`${API_BASE}/api/projects/${publicId}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Client-Token": getClientToken() },
        body: JSON.stringify({ settings }),
    });
    return parseResponse<{ project_id: string; status: string }>(res);
}

export async function proceedAIPipeline(
    publicId: string
): Promise<{ project_id: string; status: string }> {
    const res = await fetch(`${API_BASE}/api/projects/${publicId}/proceed`, {
        method: "POST",
        headers: { "X-Client-Token": getClientToken() },
    });
    return parseResponse<{ project_id: string; status: string }>(res);
}

export async function getDetailProtection(publicId: string): Promise<DetailProtectionMetadata> {
    const res = await fetch(`${API_BASE}/api/projects/${publicId}/detail-protection`, {
        headers: { "X-Client-Token": getClientToken() },
    });
    return parseResponse<DetailProtectionMetadata>(res);
}

export async function getDetailProtectionMask(publicId: string): Promise<Blob> {
    const res = await fetch(`${API_BASE}/api/projects/${publicId}/detail-protection/mask`, {
        headers: { "X-Client-Token": getClientToken() },
    });
    if (!res.ok) {
        await parseResponse<never>(res);
    }
    return res.blob();
}

export async function putDetailProtection(publicId: string, mask: Blob): Promise<DetailProtectionMetadata> {
    const res = await fetch(`${API_BASE}/api/projects/${publicId}/detail-protection`, {
        method: "PUT",
        headers: { "Content-Type": "image/png", "X-Client-Token": getClientToken() },
        body: mask,
    });
    return parseResponse<DetailProtectionMetadata>(res);
}

export async function deleteDetailProtection(publicId: string): Promise<DetailProtectionMetadata> {
    const res = await fetch(`${API_BASE}/api/projects/${publicId}/detail-protection`, {
        method: "DELETE",
        headers: { "X-Client-Token": getClientToken() },
    });
    return parseResponse<DetailProtectionMetadata>(res);
}

export async function selectPBNDifficulty(
    publicId: string,
    difficulty: PBNDifficulty,
): Promise<{ project_id: string; status: string; difficulty: PBNDifficulty }> {
    const res = await fetch(`${API_BASE}/api/projects/${publicId}/select-pbn`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Client-Token": getClientToken() },
        body: JSON.stringify({ difficulty }),
    });
    return parseResponse<{ project_id: string; status: string; difficulty: PBNDifficulty }>(res);
}

export async function resolveUser(email: string): Promise<{ exists: boolean; user?: User; requires_more_data?: boolean }> {
    const res = await fetch(`${API_BASE}/api/users/resolve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
    });
    return parseResponse<{ exists: boolean; user?: User; requires_more_data?: boolean }>(res);
}

export async function createUser(payload: { email: string; username: string; phone_number: string }): Promise<User> {
    const res = await fetch(`${API_BASE}/api/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    return parseResponse<User>(res);
}

export async function attachUser(publicId: string, userId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/api/projects/${publicId}/attach-user`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
    });
    await parseResponse<{ status: string }>(res);
}

export function buildPreviewUrl(publicId: string, fileId: string): string {
    return `${API_BASE}/api/projects/${publicId}/files/${fileId}/preview`;
}

export function buildDownloadUrl(publicId: string, fileId: string): string {
    return `${API_BASE}/api/projects/${publicId}/files/${fileId}/download`;
}
