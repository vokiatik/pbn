import type { ProjectFile } from "../api/client";
import { MAX_STEP, MIN_STEP, STEP_IDS } from "../types/steps";
import type { StepId } from "../types/types";
import { hasStepOutput } from "./previewUtils";

export function clampStep(step: number): StepId {
    return Math.min(MAX_STEP, Math.max(MIN_STEP, step)) as StepId;
}

export function getRunningStepFromStatus(status: string): StepId | null {
    const match = status.match(/^step_(\d+)_(queued|processing|ongoing|running)$/);
    return match ? clampStep(Number(match[1])) : null;
}

export function getCompletedStepFromStatus(status?: string): StepId | null {
    if (status === "completed") return MAX_STEP as StepId;

    const match = status?.match(/^step_(\d+)_completed$/);
    return match ? clampStep(Number(match[1])) : null;
}

export function stepIsRunning(status: string, step: StepId) {
    return getRunningStepFromStatus(status) === step;
}

export function stepIsCompleted(status: string, step: StepId, files: ProjectFile[]) {
    if (status === "completed") return true;

    const completedStep = getCompletedStepFromStatus(status);
    if (completedStep !== null && step <= completedStep) return true;

    return hasStepOutput(files, step);
}

export function getLastCompletedStep(status: string, files: ProjectFile[]): StepId {
    let lastCompleted = getCompletedStepFromStatus(status) ?? 0;

    for (const step of STEP_IDS) {
        if (hasStepOutput(files, step)) {
            lastCompleted = Math.max(lastCompleted, step);
        }
    }

    return clampStep(lastCompleted || MIN_STEP);
}

export function getNextRunnableStep(status: string, files: ProjectFile[]): StepId {
    const runningStep = getRunningStepFromStatus(status);
    if (runningStep !== null) return runningStep;

    const completedStep = getCompletedStepFromStatus(status);
    if (completedStep !== null) {
        return completedStep >= MAX_STEP ? (MAX_STEP as StepId) : clampStep(completedStep + 1);
    }

    for (const step of STEP_IDS) {
        if (!hasStepOutput(files, step)) return step;
    }

    return MAX_STEP as StepId;
}
