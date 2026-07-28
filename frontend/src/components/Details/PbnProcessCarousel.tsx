import { Alert, Box, Button, IconButton, Stack, Tooltip, Typography } from "@mui/material";
import { useEffect, useMemo, useState } from "react";
import type { ProjectFile } from "../../api/client";
import { buildPreviewUrl } from "../../api/client";

type PbnProcessCarouselProps = {
    publicId: string;
    files: ProjectFile[];
    qualityWarning?: string;
};

type ProcessStepDefinition = {
    fileTypes: string[];
    title: string;
    description: string;
};

type ProcessStep = ProcessStepDefinition & {
    file: ProjectFile;
};

const processStepDefinitions: ProcessStepDefinition[] = [
    {
        fileTypes: ["upload_preview", "original", "original_upload"],
        title: "Source image",
        description: "The uploaded image before paint-by-number processing.",
    },
    {
        fileTypes: ["ai_simplified"],
        title: "AI simplification",
        description: "A simplified flat-colour illustration is created from the photo.",
    },
    {
        fileTypes: ["ai_palette_preview"],
        title: "Palette trace",
        description: "Paint numbers are derived from the AI image colours.",
    },
    {
        fileTypes: ["ai_final"],
        title: "Printable PBN",
        description: "The final printable paint-by-number template preview.",
    },
];

export function PbnProcessCarousel({ publicId, files, qualityWarning }: PbnProcessCarouselProps) {
    const [activeIndex, setActiveIndex] = useState(0);

    const steps = useMemo(() => {
        return processStepDefinitions
            .map((definition) => {
                const file = definition.fileTypes
                    .map((fileType) => files.find((candidate) => candidate.file_type === fileType && candidate.mime_type.startsWith("image/")))
                    .find((candidate): candidate is ProjectFile => Boolean(candidate));
                return file ? { ...definition, file } : null;
            })
            .filter((step): step is ProcessStep => Boolean(step));
    }, [files]);

    useEffect(() => {
        setActiveIndex((current) => {
            if (steps.length === 0) return 0;
            return Math.min(current, steps.length - 1);
        });
    }, [steps.length]);

    if (steps.length === 0) {
        return (
            <Typography color="text.secondary">
                No generated outputs yet.
            </Typography>
        );
    }

    const safeActiveIndex = Math.min(activeIndex, steps.length - 1);
    const activeStep = steps[safeActiveIndex];
    const canGoBack = safeActiveIndex > 0;
    const canGoForward = safeActiveIndex < steps.length - 1;

    return (
        <Stack spacing={2.5}>
            <Box
                sx={{
                    position: "relative",
                    overflow: "hidden",
                    border: "1px solid #d7dfef",
                    borderRadius: 1,
                    bgcolor: "#f8fafc",
                    minHeight: { xs: 260, md: 420 },
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                }}
            >
                <Box
                    component="img"
                    src={buildPreviewUrl(publicId, activeStep.file.id)}
                    alt={activeStep.title}
                    sx={{
                        width: "100%",
                        maxHeight: { xs: 420, lg: 680 },
                        objectFit: "contain",
                        display: "block",
                    }}
                />

                <Box
                    sx={{
                        position: "absolute",
                        inset: "0 auto 0 0",
                        width: { xs: 76, sm: 112 },
                        display: "flex",
                        alignItems: "center",
                        pl: 1.5,
                        opacity: 0,
                        transition: "opacity 160ms ease",
                        pointerEvents: canGoBack ? "auto" : "none",
                        "&:hover, &:focus-within": { opacity: canGoBack ? 1 : 0 },
                    }}
                >
                    <Tooltip title="Previous step">
                        <IconButton
                            aria-label="Previous step"
                            disabled={!canGoBack}
                            onClick={() => setActiveIndex(Math.max(0, safeActiveIndex - 1))}
                            sx={{
                                width: 42,
                                height: 42,
                                bgcolor: "rgba(255, 255, 255, 0.08)",
                                color: "#15203a",
                                border: "1px solid rgba(21, 32, 58, 0.22)",
                                backdropFilter: "blur(4px)",
                                "&:hover": { bgcolor: "rgba(255, 255, 255, 0.22)" },
                            }}
                        >
                            {"<"}
                        </IconButton>
                    </Tooltip>
                </Box>

                <Box
                    sx={{
                        position: "absolute",
                        inset: "0 0 0 auto",
                        width: { xs: 76, sm: 112 },
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "flex-end",
                        pr: 1.5,
                        opacity: 0,
                        transition: "opacity 160ms ease",
                        pointerEvents: canGoForward ? "auto" : "none",
                        "&:hover, &:focus-within": { opacity: canGoForward ? 1 : 0 },
                    }}
                >
                    <Tooltip title="Next step">
                        <IconButton
                            aria-label="Next step"
                            disabled={!canGoForward}
                            onClick={() => setActiveIndex(Math.min(steps.length - 1, safeActiveIndex + 1))}
                            sx={{
                                width: 42,
                                height: 42,
                                bgcolor: "rgba(255, 255, 255, 0.08)",
                                color: "#15203a",
                                border: "1px solid rgba(21, 32, 58, 0.22)",
                                backdropFilter: "blur(4px)",
                                "&:hover": { bgcolor: "rgba(255, 255, 255, 0.22)" },
                            }}
                        >
                            {">"}
                        </IconButton>
                    </Tooltip>
                </Box>
            </Box>

            {qualityWarning && <Alert severity="warning">{qualityWarning}</Alert>}

            <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2}>
                <Box>
                    <Typography variant="body2" color="text.secondary">
                        Step {safeActiveIndex + 1} of {steps.length}
                    </Typography>
                    <Typography variant="h6">{activeStep.title}</Typography>
                    <Typography color="text.secondary">{activeStep.description}</Typography>
                </Box>

                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    {steps.map((step, index) => (
                        <Button
                            key={step.file.id}
                            size="small"
                            variant={index === safeActiveIndex ? "contained" : "outlined"}
                            onClick={() => setActiveIndex(index)}
                            aria-label={`Show ${step.title}`}
                            sx={{
                                width: 38,
                                height: 38,
                                minWidth: 38,
                                p: 0,
                                borderRadius: "50%",
                            }}
                        >
                            {index + 1}
                        </Button>
                    ))}
                </Stack>
            </Stack>
        </Stack>
    );
}
