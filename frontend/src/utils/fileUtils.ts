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
    const byFilename = new Map<string, ProjectFile>();

    for (const file of prev) {
        byFilename.set(file.filename, file);
    }

    for (const file of next) {
        const existing = byFilename.get(file.filename);

        if (existing) {
            byFilename.set(file.filename, mergeDefined(existing, file));
        } else {
            byFilename.set(file.filename, file as ProjectFile);
        }
    }

    return Array.from(byFilename.values());
}

export function sleep(ms: number) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}