import {
    Alert,
    Box,
    Button,
    CircularProgress,
    FormControl,
    InputLabel,
    LinearProgress,
    MenuItem,
    Paper,
    Select,
    Slider,
    Stack,
    TextField,
    ToggleButton,
    ToggleButtonGroup,
    Typography,
} from "@mui/material";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
    AISettings,
    AIQuality,
    buildDownloadUrl,
    buildPreviewUrl,
    deleteProject,
    getProject,
    Project,
    ProjectFile,
    proceedAIPipeline,
    replaceProjectImage,
    runAIPipeline,
    selectPBNDifficulty,
    PBNDifficulty,
} from "../api/client";
import { AIImageExchange } from "../components/Details/AIImageExchange";
import { CategorySelect } from "../components/Details/CategorySelect";
import { DetailProtectionEditor } from "../components/Details/DetailProtectionEditor";
import { GuidanceField } from "../components/Details/GuidanceField";
import { ImageCropEditor } from "../components/Details/ImageCropEditor";
import { PbnProcessCarousel } from "../components/Details/PbnProcessCarousel";
import { PBNDifficultyOptions } from "../components/Details/PBNDifficultyOptions";
import { ProjectFilesTable } from "../components/Details/ProjectFilesTable";
import { SuggestedElementsField } from "../components/Details/SuggestedElementsField";
import StatusChip from "../components/StatusChip";
import { getAICategoryOption, normalizeAICategory } from "../config/aiCategories";
import { subscribeToProjectEvents } from "../api/projectEvents";

const defaultSettings: AISettings = {
    provider: "openai",
    category: "illustration",
    target_palette_size: 24,
    preserve_elements: [],
    simplify_elements: [],
    prompt_guidance: "",
    page_size: "a3",
    orientation: "portrait",
    fit_mode: "cover",
    crop: null,
};

const activeProcessingStatuses = new Set([
    "ai_queued",
    "ai_processing",
    "ai_image_queued",
    "ai_image_processing",
    "pbn_queued",
    "pbn_processing",
    "pbn_options_queued",
    "pbn_options_processing",
    "pbn_selection_queued",
    "pbn_selection_processing",
]);

const validImageExt = [".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"];

export function ProjectDetailsPage() {
    const { publicId = "" } = useParams();
    const navigate = useNavigate();
    const [project, setProject] = useState<Project | null>(null);
    const [files, setFiles] = useState<ProjectFile[]>([]);
    const [settings, setSettings] = useState<AISettings>(defaultSettings);
    const [loading, setLoading] = useState(true);
    const [running, setRunning] = useState(false);
    const [replacingImage, setReplacingImage] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [progressStage, setProgressStage] = useState<string | null>(null);
    const [progressMessage, setProgressMessage] = useState<string | null>(null);
    const [progressValue, setProgressValue] = useState<number>(0);
    const [settingsDirty, setSettingsDirty] = useState(false);
    const [orientationDetected, setOrientationDetected] = useState(false);
    const [protectionDirty, setProtectionDirty] = useState(false);

    const load = async () => {
        const data = await getProject(publicId);
        setProject(data.project);
        setFiles(data.files);
    };

    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        getProject(publicId)
            .then((data) => {
                if (cancelled) return;
                setProject(data.project);
                setFiles(data.files);
                if (data.project.ai_settings && Object.keys(data.project.ai_settings).length > 0) {
                    setSettings({
                        ...data.project.ai_settings,
                        category: normalizeAICategory(data.project.ai_settings.category),
                        preserve_elements: data.project.ai_settings.preserve_elements ?? [],
                        simplify_elements: data.project.ai_settings.simplify_elements ?? [],
                    });
                }
            })
            .catch((e) => setError(e instanceof Error ? e.message : "Failed to load project"))
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [publicId]);

    useEffect(() => {
        let cancelled = false;
        const refresh = async () => {
            try {
                const data = await getProject(publicId);
                if (cancelled) return;
                setProject(data.project);
                setFiles(data.files);
                setRunning(activeProcessingStatuses.has(data.project.status));
                if (!activeProcessingStatuses.has(data.project.status)) {
                    setProgressStage(null);
                    setProgressMessage(null);
                    setProgressValue(0);
                }
            } catch {
                // A reconnect can race a backend restart; the next connection
                // or project event reconciles state again.
            }
        };
        const unsubscribe = subscribeToProjectEvents(publicId, (event) => {
            try {
                const payload = JSON.parse(event.data) as {
                    type?: string;
                    project_id?: string;
                    status?: string;
                    message?: string;
                    stage?: string;
                    value?: number;
                    progress?: number;
                    files?: ProjectFile[];
                    ai_quality?: AIQuality;
                };
                if (payload.project_id !== publicId) return;
                if (typeof payload.status === "string") {
                    const nextStatus = payload.status;
                    setProject((current) => {
                        if (!current) return current;
                        const nextProject = { ...current, status: nextStatus };
                        if ((nextStatus === "ai_failed" || nextStatus === "pbn_failed" || nextStatus === "pbn_selection_failed") && payload.message) {
                            return { ...nextProject, error_message: payload.message };
                        }
                        if (activeProcessingStatuses.has(nextStatus) || nextStatus === "ai_image_ready" || nextStatus === "pbn_options_ready" || nextStatus === "ai_completed") {
                            return { ...nextProject, error_message: undefined };
                        }
                        return nextProject;
                    });
                    setRunning(activeProcessingStatuses.has(nextStatus));
                    if (nextStatus === "ai_completed" || nextStatus === "ai_failed" || nextStatus === "pbn_failed" || nextStatus === "pbn_selection_failed" || nextStatus === "pbn_options_ready" || nextStatus === "ai_image_ready") {
                        setProgressStage(null);
                        setProgressMessage(null);
                        setProgressValue(nextStatus === "ai_completed" || nextStatus === "pbn_options_ready" || nextStatus === "ai_image_ready" ? 100 : 0);
                    }
                }
                if (payload.stage || payload.message || typeof payload.value === "number" || typeof payload.progress === "number") {
                    setProgressStage(payload.stage ?? null);
                    setProgressMessage(payload.message ?? null);
                    const nextValue = typeof payload.value === "number" ? payload.value : payload.progress;
                    if (typeof nextValue === "number") {
                        setProgressValue(Math.max(0, Math.min(100, nextValue)));
                    }
                }
                if (payload.type === "upload_preview_failed" && payload.message) {
                    setProject((current) => current ? { ...current, error_message: payload.message } : current);
                }
                if (payload.files?.length) {
                    void refresh();
                }
                if (payload.ai_quality) {
                    setProject((current) => current ? { ...current, ai_quality: payload.ai_quality } : current);
                }
            } catch {
                // ignore malformed event
            }
        }, () => { void refresh(); });
        return () => {
            cancelled = true;
            unsubscribe();
        };
    }, [publicId]);

    const sourcePreviewFile = useMemo(() => {
        return (
            files.find((file) => file.file_type === "upload_preview" && file.mime_type.startsWith("image/")) ??
            files.find((file) => file.file_type === "original" && file.mime_type.startsWith("image/")) ??
            files.find((file) => file.file_type === "original_upload" && file.mime_type.startsWith("image/")) ??
            files.find((file) => file.mime_type.startsWith("image/"))
        );
    }, [files]);
    const reviewedAIFile = useMemo(
        () => files.find((file) => file.file_type === "ai_simplified" && file.mime_type.startsWith("image/")),
        [files],
    );

    const canGenerateAI = project?.status === "uploaded" || project?.status === "ai_failed";
    const canRegenerateAI = project?.status === "ai_image_ready" || project?.status === "pbn_failed" || project?.status === "pbn_options_ready" || project?.status === "pbn_selection_failed" || project?.status === "ai_completed";
    const hasHardOption = project?.pbn_options?.some((option) => option.difficulty === "hard" && option.status === "valid");
    const canProceed = project?.status === "ai_image_ready" || project?.status === "pbn_failed" ||
        (!hasHardOption && ["pbn_options_ready", "pbn_selection_failed", "ai_completed"].includes(project?.status ?? ""));
    const isProcessingActive = Boolean(project && activeProcessingStatuses.has(project.status));
    const isAiExchangeActive = project?.status === "ai_queued" || project?.status === "ai_processing" || project?.status === "ai_image_queued" || project?.status === "ai_image_processing";
    const canReplaceImage = Boolean(project && ![...activeProcessingStatuses, "upload_preview_queued", "upload_preview_processing"].includes(project.status));
    const canEditSettings = !running && (canGenerateAI || canRegenerateAI);

    const updateSettings = (patch: Partial<AISettings>) => {
        setSettings((current) => ({ ...current, ...patch }));
        setSettingsDirty(true);
    };

    const handleGenerateAI = async () => {
        setError(null);
        setRunning(true);
        setProgressStage("queued");
        setProgressMessage("Queued for AI image generation");
        setProgressValue(0);
        try {
            await runAIPipeline(publicId, settings);
            setSettingsDirty(false);
            await load();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to start AI image generation");
        } finally {
            setRunning(false);
        }
    };

    const handleProceed = async () => {
        setError(null);
        setRunning(true);
        setProgressStage("queued");
        setProgressMessage("Queued to generate Hard PBN");
        setProgressValue(0);
        try {
            await proceedAIPipeline(publicId);
            await load();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to start PBN generation");
        } finally {
            setRunning(false);
        }
    };

    const handleDifficultySelect = async (difficulty: PBNDifficulty) => {
        setError(null);
        setRunning(true);
        setProgressStage("queued");
        setProgressMessage(`Queued to create ${difficulty} printable files`);
        setProgressValue(0);
        try {
            await selectPBNDifficulty(publicId, difficulty);
            await load();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to select PBN difficulty");
        } finally {
            setRunning(false);
        }
    };

    const handleReplaceImage = async (file: File) => {
        const validationError = validateImageFile(file);
        if (validationError) {
            setError(validationError);
            return;
        }

        setError(null);
        setReplacingImage(true);
        setProgressStage(null);
        setProgressMessage(null);
        setProgressValue(0);
        try {
            const result = await replaceProjectImage(publicId, file);
            setProject((current) => current ? { ...current, status: result.status, pipeline_version: result.pipeline_version, error_message: undefined } : current);
            setFiles(result.files);
            setSettings(defaultSettings);
            setSettingsDirty(false);
            setOrientationDetected(false);
            await load();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to change picture");
        } finally {
            setReplacingImage(false);
        }
    };

    if (loading || !project) return <Typography>Loading...</Typography>;

    const categoryOption = getAICategoryOption(settings.category);

    return (
        <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
                <Stack spacing={0.5}>
                    <Typography variant="h4" fontWeight={700}>
                        Project {project.public_id}
                    </Typography>
                    <Stack direction="row" spacing={1} alignItems="center">
                        <StatusChip status={project.status} />
                        <Typography color="text.secondary">AI-assisted workflow</Typography>
                    </Stack>
                    {isProcessingActive && (
                        <Box sx={{ mt: 1, width: { xs: "100%", sm: 420 } }}>
                            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={0.5}>
                                <Typography variant="body2" color="text.secondary">
                                    {progressMessage ?? statusProgressLabel(project.status, progressStage)}
                                </Typography>
                                <Typography variant="body2" color="text.secondary">
                                    {progressValue}%
                                </Typography>
                            </Stack>
                            <LinearProgress variant="determinate" value={progressValue} />
                        </Box>
                    )}
                </Stack>

                <Stack direction="row" spacing={1} alignItems="center">
                    <Button variant="outlined" component="label" disabled={!canReplaceImage || replacingImage}>
                        {replacingImage ? <CircularProgress size={20} /> : "Change Picture"}
                        <input
                            hidden
                            type="file"
                            accept=".png,.jpg,.jpeg,.webp,.heic,.heif,image/png,image/jpeg,image/webp,image/heic,image/heif"
                            onChange={(event) => {
                                const file = event.target.files?.[0];
                                event.target.value = "";
                                if (file) void handleReplaceImage(file);
                            }}
                        />
                    </Button>
                    <Button
                        color="error"
                        onClick={async () => {
                            await deleteProject(publicId);
                            navigate("/projects");
                        }}
                    >
                        Delete Project
                    </Button>
                </Stack>
            </Stack>

            {error && (
                <Alert severity="error" sx={{ mb: 2 }}>
                    {error}
                </Alert>
            )}

            {project.error_message && (
                <Alert severity="error" sx={{ mb: 2 }}>
                    {project.error_message}
                </Alert>
            )}

            <Stack direction={{ xs: "column", lg: "row" }} spacing={3}>
                <Paper sx={{ p: 2, width: { xs: "100%", lg: 380 }, flexShrink: 0 }}>
                    <Typography variant="h6" mb={2}>AI Generation</Typography>

                    <Stack spacing={2}>
                        <Box>
                            <Typography variant="subtitle2" mb={1}>AI provider</Typography>
                            <ToggleButtonGroup
                                exclusive
                                fullWidth
                                size="small"
                                value={settings.provider}
                                disabled={!canEditSettings}
                                onChange={(_, value: AISettings["provider"] | null) => {
                                    if (value) updateSettings({ provider: value });
                                }}
                            >
                                <ToggleButton value="openai">GPT</ToggleButton>
                                <ToggleButton value="gemini">Gemini</ToggleButton>
                            </ToggleButtonGroup>
                        </Box>

                        <CategorySelect
                            value={settings.category}
                            disabled={!canEditSettings}
                            onChange={(category) => updateSettings({ category })}
                        />

                        <Box>
                            <Typography gutterBottom>Target paint colours: {settings.target_palette_size}</Typography>
                            <Slider
                                min={8}
                                max={40}
                                step={1}
                                value={settings.target_palette_size}
                                disabled={!canEditSettings}
                                onChange={(_, value) => updateSettings({ target_palette_size: value as number })}
                            />
                        </Box>

                        <Stack direction="row" spacing={1}>
                            <FormControl fullWidth size="small">
                                <InputLabel>Page size</InputLabel>
                                <Select
                                    label="Page size"
                                    value={settings.page_size}
                                    disabled={!canEditSettings}
                                    onChange={(event) => updateSettings({ page_size: event.target.value as AISettings["page_size"] })}
                                >
                                    <MenuItem value="a3">A3</MenuItem>
                                    <MenuItem value="a4">A4</MenuItem>
                                </Select>
                            </FormControl>
                            <FormControl fullWidth size="small">
                                <InputLabel>Orientation</InputLabel>
                                <Select
                                    label="Orientation"
                                    value={settings.orientation}
                                    disabled={!canEditSettings}
                                    onChange={(event) => {
                                        setOrientationDetected(true);
                                        updateSettings({ orientation: event.target.value as AISettings["orientation"], crop: null });
                                    }}
                                >
                                    <MenuItem value="portrait">Portrait</MenuItem>
                                    <MenuItem value="landscape">Landscape</MenuItem>
                                </Select>
                            </FormControl>
                        </Stack>

                        <FormControl fullWidth size="small">
                            <InputLabel>Fit mode</InputLabel>
                            <Select
                                label="Fit mode"
                                value={settings.fit_mode}
                                disabled={!canEditSettings}
                                onChange={(event) => updateSettings({ fit_mode: event.target.value as AISettings["fit_mode"], crop: null })}
                            >
                                <MenuItem value="cover">Cover</MenuItem>
                                <MenuItem value="contain">Contain</MenuItem>
                            </Select>
                        </FormControl>

                        <SuggestedElementsField
                            label="Elements to preserve"
                            value={settings.preserve_elements}
                            suggestions={categoryOption.preserveSuggestions}
                            disabled={!canEditSettings}
                            onChange={(preserveElements) => updateSettings({ preserve_elements: preserveElements })}
                            placeholder="Type an element to preserve"
                        />

                        <SuggestedElementsField
                            label="Elements to simplify"
                            value={settings.simplify_elements}
                            suggestions={categoryOption.simplifySuggestions}
                            disabled={!canEditSettings}
                            onChange={(simplifyElements) => updateSettings({ simplify_elements: simplifyElements })}
                            placeholder="Type an element to simplify"
                        />

                        <GuidanceField
                            value={settings.prompt_guidance}
                            disabled={!canEditSettings}
                            onChange={(promptGuidance) => updateSettings({ prompt_guidance: promptGuidance })}
                        />

                        {settings.fit_mode === "cover" && sourcePreviewFile && (
                            <ImageCropEditor
                                src={buildPreviewUrl(publicId, sourcePreviewFile.id)}
                                orientation={settings.orientation}
                                value={settings.crop}
                                disabled={!canEditSettings}
                                onChange={(crop) => updateSettings({ crop })}
                                onSourceOrientation={(orientation) => {
                                    if (!orientationDetected && (!project.ai_settings || Object.keys(project.ai_settings).length === 0)) {
                                        setOrientationDetected(true);
                                        updateSettings({ orientation, crop: null });
                                    }
                                }}
                            />
                        )}

                        {settingsDirty && canProceed && (
                            <Alert severity="info">
                                Regenerate the AI image to apply changed crop or generation settings before proceeding.
                            </Alert>
                        )}

                        {project.status === "ai_image_ready" && !settingsDirty && (
                            <Alert severity="info">
                                If the AI image is still too detailed, add guidance such as larger colour areas,
                                simpler fur or texture, or a simpler background, then regenerate. Your print crop is retained.
                            </Alert>
                        )}

                        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
                            {canGenerateAI && (
                                <Button variant="contained" onClick={() => void handleGenerateAI()} disabled={running} fullWidth>
                                    {running ? <CircularProgress size={20} /> : "Generate AI image"}
                                </Button>
                            )}
                            {canRegenerateAI && (
                                <Button variant="outlined" onClick={() => void handleGenerateAI()} disabled={running} fullWidth>
                                    {running ? <CircularProgress size={20} /> : "Regenerate AI image"}
                                </Button>
                            )}
                            {canProceed && (
                                <Button variant="contained" onClick={() => void handleProceed()} disabled={running || settingsDirty || protectionDirty} fullWidth>
                                    {running ? <CircularProgress size={20} /> : "Generate Hard PBN"}
                                </Button>
                            )}
                        </Stack>
                    </Stack>
                </Paper>

                <Paper sx={{ p: 2, flex: 1, minWidth: 0 }}>
                    <Typography variant="h6" mb={2}>PBN process</Typography>
                    {reviewedAIFile && !isProcessingActive && (
                        <Box sx={{ mb: 3 }}>
                            <DetailProtectionEditor
                                publicId={publicId}
                                src={buildPreviewUrl(publicId, reviewedAIFile.id)}
                                disabled={running}
                                onDirtyChange={setProtectionDirty}
                                onSaved={load}
                            />
                        </Box>
                    )}
                    {hasHardOption && project.pbn_options ? (
                        <Stack spacing={3}>
                            <PBNDifficultyOptions
                                publicId={publicId}
                                options={project.pbn_options}
                                files={files}
                                selected={project.selected_pbn_difficulty}
                                disabled={running || isProcessingActive}
                                onSelect={handleDifficultySelect}
                            />
                            {project.selected_pbn_difficulty === "hard" && (
                                <PbnProcessCarousel
                                    publicId={publicId}
                                    files={files}
                                    qualityWarning={qualityWarning(project, settingsDirty)}
                                />
                            )}
                        </Stack>
                    ) : isAiExchangeActive ? (
                        <AIImageExchange publicId={publicId} sourceFile={sourcePreviewFile} status={project.status} />
                    ) : (
                        <PbnProcessCarousel
                            publicId={publicId}
                            files={files}
                            qualityWarning={qualityWarning(project, settingsDirty)}
                        />
                    )}
                </Paper>
            </Stack>

            <ProjectFilesTable
                publicId={publicId}
                files={files}
                onDownload={(fileId) => {
                    window.location.href = buildDownloadUrl(publicId, fileId);
                }}
            />
        </Box>
    );
}

function validateImageFile(file: File): string | null {
    const lower = file.name.toLowerCase();
    const hasValidExt = validImageExt.some((ext) => lower.endsWith(ext));
    if (!hasValidExt) return "Only PNG, JPG/JPEG, WEBP, HEIC, and HEIF files are allowed.";
    return null;
}

function statusProgressLabel(status: string, stage: string | null): string {
    if (status === "ai_queued" || status === "ai_image_queued") return "Queued for AI image generation";
    if (status === "pbn_queued") return "Queued for PBN generation";
    if (status === "pbn_options_queued") return "Queued to generate Hard PBN";
    if (status === "pbn_selection_queued") return "Queued to create printable files";
    const labels: Record<string, string> = {
        preparing_source: "Applying the approved print composition",
        generating_ai_image: "Generating simplified AI image",
        assessing_ai_image: "Checking paint-by-number source quality",
        ai_image_ready: "AI image ready for review",
        extracting_regions: "Tracing topology-aware paint regions",
        normalizing_region_palette: "Deriving the final paint palette",
        cleaning_regions: "Merging unpaintable fragments",
        validating_template: "Checking physical print requirements",
        generating_template: "Writing validated print files",
        options_ready: "Hard PBN preview is ready",
    };
    if (stage) return labels[stage] ?? stage;
    if (status === "pbn_processing") return "Processing paint-by-number outputs";
    if (status === "pbn_options_processing") return "Generating Hard PBN";
    if (status === "pbn_selection_processing") return "Creating selected printable files";
    return "Processing AI image";
}

function qualityWarning(project: Project, settingsDirty: boolean): string | undefined {
    if (project.status !== "ai_image_ready" || project.ai_quality?.status !== "warn" || settingsDirty) {
        return undefined;
    }
    return `${project.ai_quality.message} ${qualityGuidance(project.ai_quality.codes)}`.trim();
}

function qualityGuidance(codes: string[]): string {
    const guidance: string[] = [];
    if (codes.includes("palette_mismatch")) guidance.push("Ask for flatter colour areas and fewer gradients.");
    if (codes.includes("micro_detail_density")) guidance.push("Simplify fur, texture, and tiny highlights.");
    if (codes.includes("region_complexity")) guidance.push("Simplify the background and repeated patterns.");
    return guidance.join(" ");
}
