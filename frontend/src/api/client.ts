export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8080";

export interface Project {
    id: string;
    public_id: string;
    user_id?: string;
    username: string;
    client_token: string;
    original_filename: string;
    original_file_path: string;
    status: string;
    created_at: string;
    updated_at: string;
    completed_at?: string;
    deleted_at?: string;
    files_count: number;
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

export async function uploadProject(file: File): Promise<{ project_id: string; status: string }> {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/api/projects`, {
        method: "POST",
        headers: { "X-Client-Token": getClientToken() },
        body: fd,
    });
    return parseResponse<{ project_id: string; status: string }>(res);
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
