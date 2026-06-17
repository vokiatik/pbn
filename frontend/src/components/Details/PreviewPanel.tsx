import { Box, CircularProgress, Paper, Stack, Typography } from "@mui/material";
import type { ProjectFile } from "../../api/client";
import { buildPreviewUrl } from "../../api/client";
import type { StepId, StepParams } from "../../types/types";

type PreviewPanelProps = {
    publicId: string;
    previewStep: StepId;
    previewFile?: ProjectFile;
    previewLoading: boolean;
    previewVersion: number;
    pdfSettings: StepParams[8];
    showPdfFrame: boolean;
};

export function PreviewPanel({
    publicId,
    previewStep,
    previewFile,
    previewLoading,
    previewVersion,
    pdfSettings,
    showPdfFrame,
}: PreviewPanelProps) {
    const objectFit =
        pdfSettings.fit_mode === "stretch"
            ? "fill"
            : pdfSettings.fit_mode;

    return (
        <Paper sx={{ p: 2, flex: 1 }}>
            <Typography variant="h6" mb={2}>
                Preview: Step {previewStep}
            </Typography>

            {previewLoading ? (
                <Stack spacing={2} alignItems="center" justifyContent="center" sx={{ minHeight: 260 }}>
                    <CircularProgress />
                    <Typography color="text.secondary">Generating preview...</Typography>
                </Stack>
            ) : previewFile ? (
                showPdfFrame ? (
                    <Box sx={{ width: "100%", display: "flex", justifyContent: "center" }}>
                        <Box
                            sx={{
                                width: "100%",
                                maxWidth:
                                    pdfSettings.page_width_cm > pdfSettings.page_height_cm
                                        ? 760
                                        : 520,
                                aspectRatio: `${pdfSettings.page_width_cm} / ${pdfSettings.page_height_cm}`,
                                bgcolor: "white",
                                borderRadius: 2,
                                border: "1px solid #d7dfef",
                                overflow: "hidden",
                                boxShadow: 1,
                            }}
                        >
                            <Box
                                component="img"
                                src={`${buildPreviewUrl(publicId, previewFile.id)}?v=${previewVersion}`}
                                alt={previewFile.filename}
                                sx={{
                                    width: "100%",
                                    height: "100%",
                                    display: "block",
                                    objectFit,
                                }}
                            />
                        </Box>
                    </Box>
                ) : (
                    <Box
                        component="img"
                        src={`${buildPreviewUrl(publicId, previewFile.id)}?v=${previewVersion}`}
                        alt={previewFile.filename}
                        sx={{
                            width: "100%",
                            borderRadius: 2,
                            border: "1px solid #d7dfef",
                        }}
                    />
                )
            ) : (
                <Typography color="text.secondary">No image preview available for this step yet.</Typography>
            )}
        </Paper>
    );
}