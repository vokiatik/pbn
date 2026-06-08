import {
    Alert,
    Box,
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    LinearProgress,
    Paper,
    Stack,
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
} from "../api/client";
import StatusChip from "../components/StatusChip";

type EventPayload = {
    type: string;
    project_id: string;
    status?: string;
    value?: number;
    message?: string;
};

export default function ProjectDetailsPage() {
    const { publicId = "" } = useParams();
    const navigate = useNavigate();

    const [project, setProject] = useState<Project | null>(null);
    const [files, setFiles] = useState<ProjectFile[]>([]);
    const [progress, setProgress] = useState(0);
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
                    const nextStatus = payload.status;
                    setProject((prev) => (prev ? { ...prev, status: nextStatus } : prev));
                    if (nextStatus === "completed") {
                        setProgress(100);
                        void load();
                    }
                }
            } catch {
                // ignore malformed events
            }
        };

        return () => {
            ws.close();
        };
    }, [publicId]);

    const previewFile = useMemo(() => {
        const preferredOrder = ["pbn_numbered", "pbn_outline", "colored_preview"];
        for (const fileType of preferredOrder) {
            const match = files.find((f) => f.file_type === fileType);
            if (match) return match;
        }
        return files.find((f) => f.mime_type.startsWith("image/"));
    }, [files]);

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

    if (!project) {
        return <Typography>Loading...</Typography>;
    }

    return (
        <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
                <Typography variant="h4" fontWeight={700}>Project {project.public_id}</Typography>
                <Stack direction="row" spacing={1}>
                    <Button color="error" onClick={async () => {
                        await deleteProject(publicId);
                        navigate("/projects");
                    }}>
                        Delete Project
                    </Button>
                </Stack>
            </Stack>

            {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

            <Paper sx={{ p: 2, mb: 3 }}>
                <Stack direction="row" spacing={2} alignItems="center" mb={1}>
                    <Typography>Status:</Typography>
                    <StatusChip status={project.status} />
                </Stack>
                <LinearProgress variant="determinate" value={progress} sx={{ height: 10, borderRadius: 8 }} />
                <Typography mt={1} color="text.secondary">Progress: {progress}%</Typography>
            </Paper>

            <Stack direction={{ xs: "column", md: "row" }} spacing={3}>
                <Paper sx={{ p: 2, flex: 1 }}>
                    <Typography variant="h6" mb={2}>Generated Files</Typography>
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
                            {files.map((f) => (
                                <TableRow key={f.id}>
                                    <TableCell>{f.file_type}</TableCell>
                                    <TableCell>{f.filename}</TableCell>
                                    <TableCell>{(f.size_bytes / 1024).toFixed(1)} KB</TableCell>
                                    <TableCell align="right">
                                        <Stack direction="row" spacing={1} justifyContent="flex-end">
                                            <Button size="small" onClick={() => window.open(buildPreviewUrl(publicId, f.id), "_blank")}>Preview</Button>
                                            <Button size="small" variant="contained" onClick={() => void handleDownload(f.id)}>Download</Button>
                                        </Stack>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </Paper>

                <Paper sx={{ p: 2, flex: 1 }}>
                    <Typography variant="h6" mb={2}>Preview</Typography>
                    {previewFile ? (
                        <Box
                            component="img"
                            src={buildPreviewUrl(publicId, previewFile.id)}
                            alt={previewFile.filename}
                            sx={{ width: "100%", borderRadius: 2, border: "1px solid #d7dfef" }}
                        />
                    ) : (
                        <Typography color="text.secondary">No image preview available yet.</Typography>
                    )}
                </Paper>
            </Stack>

            <Dialog open={userDialogOpen} onClose={() => setUserDialogOpen(false)} fullWidth maxWidth="sm">
                <DialogTitle>Before download, share contact info</DialogTitle>
                <DialogContent>
                    <Stack spacing={2} mt={1}>
                        <TextField
                            label="Email"
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            required
                        />
                        {needMoreData && (
                            <>
                                <TextField
                                    label="Username"
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                />
                                <TextField
                                    label="Phone number"
                                    value={phoneNumber}
                                    onChange={(e) => setPhoneNumber(e.target.value)}
                                />
                            </>
                        )}
                    </Stack>
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => {
                        if (downloadFileId) completeDownload(downloadFileId);
                        setUserDialogOpen(false);
                    }}>
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
