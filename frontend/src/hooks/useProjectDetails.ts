import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Project, ProjectFile } from "../api/client";
import {
    API_BASE,
    attachUser,
    buildDownloadUrl,
    createUser,
    getProject,
    resolveUser,
    runProjectStep,
} from "../api/client";
import { MAX_STEP, defaultParams } from "../types/steps";
import type { EventPayload, SetStepParam, StepId, StepParams } from "../types/types";
import { mergeFiles, sleep } from "../utils/fileUtils";
import { findPreviewFile, hasStepOutput } from "../utils/previewUtils";
import {
    clampStep,
    getCompletedStepFromStatus,
    getLastCompletedStep,
    getNextRunnableStep,
    stepIsRunning,
} from "../utils/stepUtils";

type LoadOptions = {
    syncSteps?: boolean;
    merge?: boolean;
};

export function useProjectDetails(publicId: string) {
    const [project, setProject] = useState<Project | null>(null);
    const [files, setFiles] = useState<ProjectFile[]>([]);
    const [progress, setProgress] = useState(0);
    const [activeStep, setActiveStep] = useState<StepId>(1);
    const [previewStep, setPreviewStep] = useState<StepId>(1);
    const [params, setParams] = useState<StepParams>(defaultParams);
    const [error, setError] = useState<string | null>(null);

    const [userDialogOpen, setUserDialogOpen] = useState(false);
    const [downloadFileId, setDownloadFileId] = useState<string | null>(null);
    const [email, setEmail] = useState("");
    const [username, setUsername] = useState("");
    const [phoneNumber, setPhoneNumber] = useState("");
    const [needMoreData, setNeedMoreData] = useState(false);

    const [previewLoading, setPreviewLoading] = useState(false);
    const [previewVersion, setPreviewVersion] = useState(Date.now());

    const lastRunStepRef = useRef<StepId | null>(null);
    const filesRef = useRef<ProjectFile[]>([]);
    const previewFileBeforeRunRef = useRef<string | null>(null);

    const syncStepsFromProject = useCallback((status: string, projectFiles: ProjectFile[]) => {
        setActiveStep(getNextRunnableStep(status, projectFiles));
        setPreviewStep(getLastCompletedStep(status, projectFiles));
    }, []);

    const load = useCallback(
        async ({ syncSteps = false, merge = false }: LoadOptions = {}) => {
            const res = await getProject(publicId);
            const nextFiles = merge ? mergeFiles(filesRef.current, res.files) : res.files;

            filesRef.current = nextFiles;
            setProject(res.project);
            setFiles(nextFiles);
            setPreviewVersion(Date.now());

            if (res.project.status === "completed") {
                setProgress(100);
            }

            if (syncSteps) {
                syncStepsFromProject(res.project.status, nextFiles);
            }

            return { ...res, files: nextFiles };
        },
        [publicId, syncStepsFromProject]
    );

    const reloadAfterStepCompleted = useCallback(
        async (eventStatus?: string, fallbackCompletedStep?: StepId | null) => {
            const expectedCompletedStep = getCompletedStepFromStatus(eventStatus) ?? fallbackCompletedStep ?? null;
            let lastError: unknown = null;

            const minAttempts = expectedCompletedStep === null ? 1 : 5;

            for (let attempt = 0; attempt < 5; attempt += 1) {
                await sleep(350 * (attempt + 1));

                try {
                    const res = await load({ merge: true });
                    const loadedCompletedStep = getCompletedStepFromStatus(res.project.status);
                    const inferredCompletedStep = getLastCompletedStep(res.project.status, res.files);
                    const completedStep = expectedCompletedStep ?? loadedCompletedStep ?? inferredCompletedStep;

                    const latestPreviewFile = findPreviewFile(res.files, completedStep);
                    const previousPreviewFileId = previewFileBeforeRunRef.current;
                    const hasExpectedOutput =
                        expectedCompletedStep === null ||
                        res.project.status === "completed" ||
                        hasStepOutput(res.files, expectedCompletedStep);
                    const outputDefinitelyChanged =
                        previousPreviewFileId === null ||
                        latestPreviewFile?.id === undefined ||
                        latestPreviewFile.id !== previousPreviewFileId;

                    setPreviewStep(completedStep);
                    setActiveStep(completedStep >= MAX_STEP ? (MAX_STEP as StepId) : clampStep(completedStep + 1));
                    setPreviewVersion(Date.now());

                    if (hasExpectedOutput && (outputDefinitelyChanged || attempt + 1 >= minAttempts)) {
                        lastRunStepRef.current = null;
                        previewFileBeforeRunRef.current = null;
                        return;
                    }
                } catch (e) {
                    lastError = e;
                }
            }

            lastRunStepRef.current = null;
            previewFileBeforeRunRef.current = null;

            if (lastError) {
                throw lastError;
            }
        },
        [load]
    );

    useEffect(() => {
        void load({ syncSteps: true }).catch((e) =>
            setError(e instanceof Error ? e.message : "Failed to load project")
        );
    }, [load]);

    useEffect(() => {
        if (!publicId) return;

        const wsBase = API_BASE.replace(/^http/, "ws");
        const ws = new WebSocket(`${wsBase}/ws?project_id=${publicId}`);

        ws.onmessage = (event) => {
            try {
                const payload = JSON.parse(event.data) as EventPayload;

                if (payload.project_id && payload.project_id !== publicId) return;

                if (typeof payload.value === "number") {
                    setProgress(payload.value);
                }

                if (typeof payload.status === "string") {
                    setProject((prev) => (prev ? { ...prev, status: payload.status! } : prev));
                }

                if (payload.files) {
                    const nextFiles = mergeFiles(filesRef.current, payload.files!);
                    filesRef.current = nextFiles;
                    setFiles(nextFiles);
                    setPreviewVersion(Date.now());
                }

                if (payload.type === "upload_preview_processing") {
                    setPreviewLoading(true);
                }

                if (payload.type === "upload_preview_completed") {
                    setPreviewLoading(false);
                    setPreviewVersion(Date.now());

                    void load({ merge: true }).catch((e) =>
                        setError(e instanceof Error ? e.message : "Failed to reload project")
                    );
                }

                if (payload.type === "step_completed" || payload.type === "completed") {
                    setPreviewLoading(false);

                    void reloadAfterStepCompleted(payload.status, lastRunStepRef.current).catch((e) =>
                        setError(e instanceof Error ? e.message : "Failed to reload project")
                    );
                }

                if (payload.type === "failed" || payload.type === "upload_preview_failed") {
                    lastRunStepRef.current = null;
                    previewFileBeforeRunRef.current = null;
                    setPreviewLoading(false);
                    setError(payload.message ?? "Processing failed");
                }
            } catch {
                // ignore malformed events
            }
        };

        return () => ws.close();
    }, [publicId, load, reloadAfterStepCompleted]);

    const previewFile = useMemo(() => {
        return findPreviewFile(files, previewStep);
    }, [files, previewStep]);

    const currentStatus = project?.status ?? "uploaded";
    const running = stepIsRunning(currentStatus, activeStep);

    const selectStep = useCallback((step: StepId) => {
        setActiveStep(step);
        setPreviewStep(step);
    }, []);

    const runCurrentStep = useCallback(async () => {
        setError(null);
        setPreviewLoading(true);
        lastRunStepRef.current = activeStep;
        previewFileBeforeRunRef.current = findPreviewFile(filesRef.current, activeStep)?.id ?? null;

        try {
            await runProjectStep(publicId, activeStep, params[activeStep] as Record<string, unknown>);

            setProject((prev) =>
                prev ? { ...prev, status: `step_${activeStep}_queued` } : prev
            );
        } catch (e) {
            lastRunStepRef.current = null;
            previewFileBeforeRunRef.current = null;
            setPreviewLoading(false);
            setError(e instanceof Error ? e.message : "Failed to run step");
        }
    }, [activeStep, params, publicId]);

    const completeDownload = useCallback(
        (fileId: string) => {
            window.open(buildDownloadUrl(publicId, fileId), "_blank", "noopener,noreferrer");
        },
        [publicId]
    );

    const handleDownload = useCallback(
        async (fileId: string) => {
            if (!project) return;

            if (project.user_id) {
                completeDownload(fileId);
                return;
            }

            setDownloadFileId(fileId);
            setUserDialogOpen(true);
        },
        [completeDownload, project]
    );

    const handleResolveAndContinue = useCallback(async () => {
        if (!project || !downloadFileId) return;

        try {
            const resolved = await resolveUser(email);

            if (resolved.exists && resolved.user) {
                await attachUser(publicId, resolved.user.id);
                setUserDialogOpen(false);
                completeDownload(downloadFileId);
                await load({ merge: true });
                return;
            }

            setNeedMoreData(true);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to resolve user");
        }
    }, [completeDownload, downloadFileId, email, load, project, publicId]);

    const handleCreateUserAndDownload = useCallback(async () => {
        if (!project || !downloadFileId) return;

        try {
            const user = await createUser({
                email,
                username,
                phone_number: phoneNumber,
            });

            await attachUser(publicId, user.id);
            setUserDialogOpen(false);
            completeDownload(downloadFileId);
            await load({ merge: true });
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to create user");
        }
    }, [completeDownload, downloadFileId, email, load, phoneNumber, project, publicId, username]);

    const handleSkipUserDialog = useCallback(() => {
        if (downloadFileId) completeDownload(downloadFileId);
        setUserDialogOpen(false);
    }, [completeDownload, downloadFileId]);

    const setStepParam: SetStepParam = useCallback((step, key, value) => {
        setParams((prev) => ({
            ...prev,
            [step]: {
                ...prev[step],
                [key]: value,
            },
        }));
    }, []);

    return {
        project,
        files,
        progress,
        activeStep,
        previewStep,
        params,
        error,
        previewLoading,
        previewVersion,
        previewFile,
        running,
        userDialogOpen,
        email,
        username,
        phoneNumber,
        needMoreData,
        selectStep,
        runCurrentStep,
        handleDownload,
        handleResolveAndContinue,
        handleCreateUserAndDownload,
        handleSkipUserDialog,
        setStepParam,
        setUserDialogOpen,
        setEmail,
        setUsername,
        setPhoneNumber,
    };
}
