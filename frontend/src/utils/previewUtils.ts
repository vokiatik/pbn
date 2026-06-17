import type { ProjectFile } from "../api/client";
import { steps } from "../types/steps";
import type { StepId } from "../types/types";

export function isImage(file: ProjectFile) {
    return (
        file.mime_type.startsWith("image/") &&
        file.mime_type !== "image/heic" &&
        file.mime_type !== "image/heif"
    );
}

function findLatest(files: ProjectFile[], predicate: (file: ProjectFile) => boolean) {
    for (let i = files.length - 1; i >= 0; i -= 1) {
        const file = files[i];
        if (predicate(file)) return file;
    }

    return undefined;
}

export function findUploadPreview(files: ProjectFile[]): ProjectFile | undefined {
    return findLatest(
        files,
        (file) => isImage(file) && file.file_type === "upload_preview"
    );
}

export function hasStepOutput(files: ProjectFile[], step: StepId) {
    const meta = steps.find((s) => s.id === step);
    if (!meta) return false;

    return files.some((file) => meta.fileTypes.includes(file.file_type));
}

export function findPreviewFile(files: ProjectFile[], previewStep: StepId): ProjectFile | undefined {
    const meta = steps.find((s) => s.id === previewStep);

    if (meta) {
        for (const previewType of meta.previewTypes) {
            const candidate = files.find((file) => file.file_type === previewType && isImage(file));

            if (candidate) return candidate;
        }
    }

    if (previewStep === 1) {
        return findUploadPreview(files);
    }

    return undefined;
}
