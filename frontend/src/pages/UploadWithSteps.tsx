import {
    Alert,
    Box,
    Button,
    Chip,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Divider,
    FormControlLabel,
    LinearProgress,
    Paper,
    Stack,
    Step,
    StepLabel,
    Stepper,
    Switch,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    TextField,
    Typography,
} from "@mui/material";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
    API_BASE,
    attachUser,
    buildDownloadUrl,
    buildPreviewUrl,
    createUser,
    deleteProject,
    getProject,
    Project,
    ProjectFile,
    resolveUser,
    runProjectStep,
} from "../api/client";
import StatusChip from "../components/StatusChip";

type EventPayload = {
    type: string;
    project_id: string;
    status?: string;
    step?: number;
    value?: number;
    message?: string;
};

type StepParams = {
    1: {
        points_per_side: number;
        pred_iou_thresh: number;
        stability_score_thresh: number;
        min_mask_region_area: number;
        min_area_ratio: number;
        max_area_ratio: number;
        dedupe_iou: number;
    };
    2: {
        colors_per_object: number;
        background_colors: number;
        min_region_area: number;
        process_background: boolean;
        max_objects: number;
    };
    3: {
        palette_size: number;
    };
    4: {
        min_region_area: number;
        split_same_color_neighbors: boolean;
    };
    5: {
        line_thickness: number;
        font_size: number;
        min_number_area: number;
    };
    6: {
        page_width_cm: number;
        page_height_cm: number;
        dpi: number;
    };
};

const defaultParams: StepParams = {
    1: {
        points_per_side: 32,
        pred_iou_thresh: 0.88,
        stability_score_thresh: 0.92,
        min_mask_region_area: 400,
        min_area_ratio: 0.002,
        max_area_ratio: 0.8,
        dedupe_iou: 0.92,
    },
    2: {
        colors_per_object: 5,
        background_colors: 6,
        min_region_area: 300,
        process_background: true,
        max_objects: 80,
    },
    3: {
        palette_size: 30,
    },
    4: {
        min_region_area: 250,
        split_same_color_neighbors: false,
    },
    5: {
        line_thickness: 1,
        font_size: 14,
        min_number_area: 100,
    },
    6: {
        page_width_cm: 29.7,
        page_height_cm: 42,
        dpi: 300,
    },
};

const steps = [
    { id: 1, title: "Object masks", previewTypes: ["step1_overlay", "step1_labels"] },
    { id: 2, title: "Smooth objects", previewTypes: ["step2_step2_smoothed", "step2_covered_mask"] },
    { id: 3, title: "Global palette", previewTypes: ["step3_step3_palette_image", "step3_palette_preview"] },
    { id: 4, title: "Regions cleanup", previewTypes: ["step4_step4_region_color_image", "step4_step4_region_ids"] },
    { id: 5, title: "Template", previewTypes: ["step5_pbn_template", "step5_pbn_colored_debug", "step5_palette_sheet"] },
    { id: 6, title: "PDF export", previewTypes: ["step6_pbn_template_A3_preview"] },
];

function isImage(file: ProjectFile) {
    return file.mime_type.startsWith("image/");
}

function findPreviewFile(files: ProjectFile[], activeStep: number): ProjectFile | undefined {
    const step = steps.find((s) => s.id === activeStep);

    if (step) {
        for (const fileType of step.previewTypes) {
            const match = files.find((f) => f.file_type === fileType);
            if (match) return match;
        }

        const imageFromStep = files.find((f) => f.file_type.startsWith(`step${activeStep}_`) && isImage(f));
        if (imageFromStep) return imageFromStep;
    }

    const preferred = [
        "step5_pbn_template",
        "step4_step4_region_color_image",
        "step3_step3_palette_image",
        "step2_step2_smoothed",
        "step1_overlay",
    ];

    for (const fileType of preferred) {
        const match = files.find((f) => f.file_type === fileType);
        if (match) return match;
    }

    return files.find(isImage);
}

function stepIsRunning(status: string, step: number) {
    return status === `step_${step}_queued` || status === `step_${step}_processing`;
}

function stepIsCompleted(status: string, step: number, files: ProjectFile[]) {
    if (status === "completed" && step === 6) return true;
    if (status === `step_${step}_completed`) return true;
    return files.some((f) => f.file_type.startsWith(`step${step}_`));
}

function NumberField({
    label,
    value,
    onChange,
    step = 1,
    min,
    max,
}: {
    label: string;
    value: number;
    onChange: (value: number) => void;
    step?: number;
    min?: number;
    max?: number;
}) {
    return (
        <TextField
            label={label}
            type="number"
            size="small"
            value={value}
            inputProps={{ step, min, max }}
            onChange={(e) => onChange(Number(e.target.value))}
            fullWidth
        />
    );
}

export function ProjectDetailsPageNew() {
    const { publicId = "" } = useParams();
    const navigate = useNavigate();

    const [project, setProject] = useState<Project | null>(null);
    const [files, setFiles] = useState<ProjectFile[]>([]);
    const [progress, setProgress] = useState(0);
    const [activeStep, setActiveStep] = useState(1);
    const [params, setParams] = useState<StepParams>(defaultParams);
    const [error, setError] = useState<string | null>(null);

    const [userDialogOpen, setUserDialogOpen] = useState(false);
    const [downloadFileId, setDownloadFileId] = useState<string | null>(null);
    const [email, setEmail] = useState("");
    const [username, setUsername] = useState("");
    const [phoneNumber, setPhoneNumber] = useState("");
    const [needMoreData, setNeedMoreData] = useState(false);

    const load = async () => {
        const res = await getProject(publicId);
        setProject(res.project);
        setFiles(res.files);
        if (res.project.status === "completed") setProgress(100);
    };

    useEffect(() => {
        void load().catch((e) => setError(e instanceof Error ? e.message : "Failed to load project"));
    }, [publicId]);

    useEffect(() => {
        if (!publicId) return;

        const wsBase = API_BASE.replace("http", "ws");
        const ws = new WebSocket(`${wsBase}/ws?project_id=${publicId}`);

        ws.onmessage = (event) => {
            try {
                const payload = JSON.parse(event.data) as EventPayload;

                if (payload.type === "progress" && typeof payload.value === "number") {
                    setProgress(payload.value);
                }

                if (typeof payload.status === "string") {
                    setProject((prev) => (prev ? { ...prev, status: payload.status! } : prev));
                }

                if (
                    payload.type === "step_completed" ||
                    payload.type === "completed" ||
                    payload.type === "failed"
                ) {
                    void load();
                }
            } catch {
                // ignore malformed ws event
            }
        };

        return () => ws.close();
    }, [publicId]);

    const previewFile = useMemo(() => {
        return findPreviewFile(files, activeStep);
    }, [files, activeStep]);

    const currentStatus = project?.status ?? "uploaded";
    const running = stepIsRunning(currentStatus, activeStep);

    const runCurrentStep = async () => {
        setError(null);

        try {
            await runProjectStep(
                publicId,
                activeStep,
                params[activeStep as keyof StepParams] as Record<string, unknown>
            );

            setProject((prev) =>
                prev ? { ...prev, status: `step_${activeStep}_queued` } : prev
            );
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to run step");
        }
    };

    const completeDownload = (fileId: string) => {
        window.open(buildDownloadUrl(publicId, fileId), "_blank", "noopener,noreferrer");
    };

    const handleDownload = async (fileId: string) => {
        if (!project) return;

        if (project.user_id) {
            completeDownload(fileId);
            return;
        }

        setDownloadFileId(fileId);
        setUserDialogOpen(true);
    };

    const handleResolveAndContinue = async () => {
        if (!project || !downloadFileId) return;

        try {
            const resolved = await resolveUser(email);

            if (resolved.exists && resolved.user) {
                await attachUser(publicId, resolved.user.id);
                setUserDialogOpen(false);
                completeDownload(downloadFileId);
                await load();
                return;
            }

            setNeedMoreData(true);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to resolve user");
        }
    };

    const handleCreateUserAndDownload = async () => {
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
            await load();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Failed to create user");
        }
    };

    const setStepParam = <TStep extends keyof StepParams, TKey extends keyof StepParams[TStep]>(
        step: TStep,
        key: TKey,
        value: StepParams[TStep][TKey]
    ) => {
        setParams((prev) => ({
            ...prev,
            [step]: {
                ...prev[step],
                [key]: value,
            },
        }));
    };

    if (!project) return <Typography>Loading...</Typography>;

    return (
        <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
                <Typography variant="h4" fontWeight={700}>
                    Project {project.public_id}
                </Typography>

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

            {error && (
                <Alert severity="error" sx={{ mb: 2 }}>
                    {error}
                </Alert>
            )}

            <Paper sx={{ p: 2, mb: 3 }}>
                <Stack direction="row" spacing={2} alignItems="center" mb={1}>
                    <Typography>Status:</Typography>
                    <StatusChip status={project.status} />
                    {running && <CircularProgress size={18} />}
                </Stack>

                <LinearProgress variant="determinate" value={progress} sx={{ height: 10, borderRadius: 8 }} />
                <Typography mt={1} color="text.secondary">
                    Progress: {progress}%
                </Typography>
            </Paper>

            <Paper sx={{ p: 2, mb: 3 }}>
                <Stepper activeStep={activeStep - 1} alternativeLabel>
                    {steps.map((s) => (
                        <Step key={s.id} completed={stepIsCompleted(project.status, s.id, files)}>
                            <StepLabel onClick={() => setActiveStep(s.id)} sx={{ cursor: "pointer" }}>
                                {s.title}
                            </StepLabel>
                        </Step>
                    ))}
                </Stepper>
            </Paper>

            <Stack direction={{ xs: "column", lg: "row" }} spacing={3}>
                <Paper sx={{ p: 2, flex: 1 }}>
                    <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
                        <Box>
                            <Typography variant="h6">
                                Step {activeStep}: {steps.find((s) => s.id === activeStep)?.title}
                            </Typography>

                            <Typography color="text.secondary" variant="body2">
                                Tune parameters, run this step, inspect preview, then continue.
                            </Typography>
                        </Box>

                        <Chip label={`Step ${activeStep}`} />
                    </Stack>

                    <Divider sx={{ mb: 2 }} />

                    <Stack spacing={2}>
                        {activeStep === 1 && (
                            <>
                                <NumberField label="points_per_side" value={params[1].points_per_side} onChange={(v) => setStepParam(1, "points_per_side", v)} />
                                <NumberField label="pred_iou_thresh" value={params[1].pred_iou_thresh} step={0.01} min={0} max={1} onChange={(v) => setStepParam(1, "pred_iou_thresh", v)} />
                                <NumberField label="stability_score_thresh" value={params[1].stability_score_thresh} step={0.01} min={0} max={1} onChange={(v) => setStepParam(1, "stability_score_thresh", v)} />
                                <NumberField label="min_mask_region_area" value={params[1].min_mask_region_area} onChange={(v) => setStepParam(1, "min_mask_region_area", v)} />
                                <NumberField label="min_area_ratio" value={params[1].min_area_ratio} step={0.001} min={0} max={1} onChange={(v) => setStepParam(1, "min_area_ratio", v)} />
                                <NumberField label="max_area_ratio" value={params[1].max_area_ratio} step={0.01} min={0} max={1} onChange={(v) => setStepParam(1, "max_area_ratio", v)} />
                                <NumberField label="dedupe_iou" value={params[1].dedupe_iou} step={0.01} min={0} max={1} onChange={(v) => setStepParam(1, "dedupe_iou", v)} />
                            </>
                        )}

                        {activeStep === 2 && (
                            <>
                                <NumberField label="colors_per_object" value={params[2].colors_per_object} onChange={(v) => setStepParam(2, "colors_per_object", v)} />
                                <NumberField label="background_colors" value={params[2].background_colors} onChange={(v) => setStepParam(2, "background_colors", v)} />
                                <NumberField label="min_region_area" value={params[2].min_region_area} onChange={(v) => setStepParam(2, "min_region_area", v)} />
                                <NumberField label="max_objects" value={params[2].max_objects} onChange={(v) => setStepParam(2, "max_objects", v)} />
                                <FormControlLabel
                                    control={
                                        <Switch
                                            checked={params[2].process_background}
                                            onChange={(e) => setStepParam(2, "process_background", e.target.checked)}
                                        />
                                    }
                                    label="Process background"
                                />
                            </>
                        )}

                        {activeStep === 3 && (
                            <NumberField label="palette_size" value={params[3].palette_size} min={8} max={60} onChange={(v) => setStepParam(3, "palette_size", v)} />
                        )}

                        {activeStep === 4 && (
                            <>
                                <NumberField label="min_region_area" value={params[4].min_region_area} onChange={(v) => setStepParam(4, "min_region_area", v)} />
                                <FormControlLabel
                                    control={
                                        <Switch
                                            checked={params[4].split_same_color_neighbors}
                                            onChange={(e) => setStepParam(4, "split_same_color_neighbors", e.target.checked)}
                                        />
                                    }
                                    label="Split same-color touching neighbors"
                                />
                            </>
                        )}

                        {activeStep === 5 && (
                            <>
                                <NumberField label="line_thickness" value={params[5].line_thickness} min={1} max={5} onChange={(v) => setStepParam(5, "line_thickness", v)} />
                                <NumberField label="font_size" value={params[5].font_size} min={6} max={40} onChange={(v) => setStepParam(5, "font_size", v)} />
                                <NumberField label="min_number_area" value={params[5].min_number_area} onChange={(v) => setStepParam(5, "min_number_area", v)} />
                            </>
                        )}

                        {activeStep === 6 && (
                            <>
                                <NumberField label="page_width_cm" value={params[6].page_width_cm} step={0.1} onChange={(v) => setStepParam(6, "page_width_cm", v)} />
                                <NumberField label="page_height_cm" value={params[6].page_height_cm} step={0.1} onChange={(v) => setStepParam(6, "page_height_cm", v)} />
                                <NumberField label="dpi" value={params[6].dpi} min={72} max={600} onChange={(v) => setStepParam(6, "dpi", v)} />
                                <Stack direction="row" spacing={1}>
                                    <Button size="small" onClick={() => {
                                        setStepParam(6, "page_width_cm", 29.7);
                                        setStepParam(6, "page_height_cm", 42);
                                    }}>
                                        A3 Portrait
                                    </Button>
                                    <Button size="small" onClick={() => {
                                        setStepParam(6, "page_width_cm", 42);
                                        setStepParam(6, "page_height_cm", 29.7);
                                    }}>
                                        A3 Landscape
                                    </Button>
                                </Stack>
                            </>
                        )}

                        <Button variant="contained" onClick={() => void runCurrentStep()} disabled={running}>
                            {running ? "Running..." : `Run Step ${activeStep}`}
                        </Button>

                        <Stack direction="row" spacing={1}>
                            <Button disabled={activeStep === 1} onClick={() => setActiveStep((s) => Math.max(1, s - 1))}>
                                Previous
                            </Button>
                            <Button disabled={activeStep === 6} onClick={() => setActiveStep((s) => Math.min(6, s + 1))}>
                                Next
                            </Button>
                        </Stack>
                    </Stack>
                </Paper>

                <Paper sx={{ p: 2, flex: 1 }}>
                    <Typography variant="h6" mb={2}>
                        Preview
                    </Typography>

                    {previewFile ? (
                        <Box
                            component="img"
                            src={buildPreviewUrl(publicId, previewFile.id)}
                            alt={previewFile.filename}
                            sx={{ width: "100%", borderRadius: 2, border: "1px solid #d7dfef" }}
                        />
                    ) : (
                        <Typography color="text.secondary">
                            No preview for this step yet.
                        </Typography>
                    )}
                </Paper>
            </Stack>

            <Paper sx={{ p: 2, mt: 3 }}>
                <Typography variant="h6" mb={2}>
                    Files
                </Typography>

                <Table size="small">
                    <TableHead>
                        <TableRow>
                            <TableCell>Type</TableCell>
                            <TableCell>Name</TableCell>
                            <TableCell>Size</TableCell>
                            <TableCell align="right">Actions</TableCell>
                        </TableRow>
                    </TableHead>

                    <TableBody>
                        {files.map((file) => (
                            <TableRow key={file.id}>
                                <TableCell>{file.file_type}</TableCell>
                                <TableCell>{file.filename}</TableCell>
                                <TableCell>{(file.size_bytes / 1024).toFixed(1)} KB</TableCell>
                                <TableCell align="right">
                                    <Stack direction="row" spacing={1} justifyContent="flex-end">
                                        <Button size="small" onClick={() => window.open(buildPreviewUrl(publicId, file.id), "_blank")}>
                                            Preview
                                        </Button>
                                        <Button size="small" variant="contained" onClick={() => void handleDownload(file.id)}>
                                            Download
                                        </Button>
                                    </Stack>
                                </TableCell>
                            </TableRow>
                        ))}
                    </TableBody>
                </Table>
            </Paper>

            <Dialog open={userDialogOpen} onClose={() => setUserDialogOpen(false)} fullWidth maxWidth="sm">
                <DialogTitle>Before download, share contact info</DialogTitle>

                <DialogContent>
                    <Stack spacing={2} mt={1}>
                        <TextField label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />

                        {needMoreData && (
                            <>
                                <TextField label="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
                                <TextField label="Phone number" value={phoneNumber} onChange={(e) => setPhoneNumber(e.target.value)} />
                            </>
                        )}
                    </Stack>
                </DialogContent>

                <DialogActions>
                    <Button
                        onClick={() => {
                            if (downloadFileId) completeDownload(downloadFileId);
                            setUserDialogOpen(false);
                        }}
                    >
                        Skip
                    </Button>

                    {!needMoreData ? (
                        <Button variant="contained" onClick={() => void handleResolveAndContinue()}>
                            Continue
                        </Button>
                    ) : (
                        <Button variant="contained" onClick={() => void handleCreateUserAndDownload()}>
                            Save and Download
                        </Button>
                    )}
                </DialogActions>
            </Dialog>
        </Box>
    );
}