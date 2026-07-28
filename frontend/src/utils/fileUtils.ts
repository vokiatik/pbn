import type { ProjectFile } from "../api/client";

type ProjectFileUpdate = Partial<ProjectFile> & Pick<ProjectFile, "filename">;

function mergeDefined<T extends object>(prev: T, next: Partial<T>): T {
    const merged = { ...prev };

    for (const [key, value] of Object.entries(next) as [keyof T, T[keyof T]][]) {
        if (value !== undefined) {
            merged[key] = value;
        }
    }

    return merged;
}

export function mergeFiles(
    prev: ProjectFile[],
    next: ProjectFileUpdate[],
): ProjectFile[] {
    const byStableKey = new Map<string, ProjectFile>();

    for (const file of prev) {
        byStableKey.set(fileMergeKey(file), file);
    }

    for (const file of next) {
        const key = fileMergeKey(file);
        const existing = byStableKey.get(key);

        if (existing) {
            byStableKey.set(key, mergeDefined(existing, file));
        } else {
            byStableKey.set(key, file as ProjectFile);
        }
    }

    return Array.from(byStableKey.values());
}

export function sleep(ms: number) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function fileMergeKey(file: ProjectFileUpdate): string {
    if (file.file_type) return `type:${file.file_type}`;
    if (file.id) return `id:${file.id}`;
    if (file.file_path) return `path:${file.file_path}`;
    return `filename:${file.filename}`;
}
