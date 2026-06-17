import { Alert, Box, Button, CircularProgress, Paper, Typography } from "@mui/material";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { uploadProject } from "../api/client";
const validExt = [".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"];

function validateFile(file: File): string | null {
    const lower = file.name.toLowerCase();
    const hasValidExt = validExt.some((ext) => lower.endsWith(ext));

    if (!hasValidExt) return "Only PNG, JPG/JPEG, WEBP, HEIC, and HEIF files are allowed.";

    return null;
}

export function UploadPage() {
    const [dragActive, setDragActive] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const navigate = useNavigate();

    const startUpload = async (file: File) => {
        const msg = validateFile(file);

        if (msg) {
            setError(msg);
            return;
        }

        setError(null);
        setIsUploading(true);

        try {
            const result = await uploadProject(file);
            navigate(`/projects/${result.project_id}`);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Upload failed");
        } finally {
            setIsUploading(false);
        }
    };

    return (
        <Box>
            <Typography variant="h4" fontWeight={700} gutterBottom>
                Create Paint-by-Number Project
            </Typography>

            <Typography color="text.secondary" mb={3}>
                Upload an image first. Generation will not start automatically; you will control every pipeline step.
            </Typography>

            <Paper
                sx={{
                    border: `2px dashed ${dragActive ? "#f05d23" : "#9aa8c7"}`,
                    borderRadius: 4,
                    p: 6,
                    textAlign: "center",
                    backgroundColor: dragActive ? "#fff4ee" : "#fffdf9",
                    transition: "all 160ms ease",
                    cursor: "pointer",
                }}
                onDragOver={(e) => {
                    e.preventDefault();
                    setDragActive(true);
                }}
                onDragLeave={() => setDragActive(false)}
                onDrop={(e) => {
                    e.preventDefault();
                    setDragActive(false);
                    const file = e.dataTransfer.files[0];
                    if (file) void startUpload(file);
                }}
            >
                <Typography variant="h6" gutterBottom>
                    Drop PNG, JPEG, HEIC, HEIF or WEBP here
                </Typography>

                <Typography mb={2}>or</Typography>

                <Button variant="contained" component="label" disabled={isUploading}>
                    Choose File
                    <input
                        hidden
                        type="file"
                        accept=".png,.jpg,.jpeg,.webp,.heic,.heif,image/png,image/jpeg,image/webp,image/heic,image/heif"
                        onChange={(e) => {
                            const file = e.target.files?.[0];
                            if (file) void startUpload(file);
                        }}
                    />
                </Button>

                {isUploading && (
                    <Box mt={3} display="flex" gap={1} justifyContent="center" alignItems="center">
                        <CircularProgress size={18} />
                        <Typography>Uploading image...</Typography>
                    </Box>
                )}
            </Paper>

            {error && (
                <Alert severity="error" sx={{ mt: 2 }}>
                    {error}
                </Alert>
            )}
        </Box>
    );
}