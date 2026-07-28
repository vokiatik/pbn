import { Box, LinearProgress, Stack, Typography } from "@mui/material";
import { buildPreviewUrl, ProjectFile } from "../../api/client";

type Props = {
    publicId: string;
    sourceFile?: ProjectFile;
    status: string;
};

const activeStatuses = new Set(["ai_queued", "ai_processing", "ai_image_queued", "ai_image_processing"]);

export function AIImageExchange({ publicId, sourceFile, status }: Props) {
    if (!activeStatuses.has(status)) return null;

    const hasSourceImage = Boolean(sourceFile?.mime_type.startsWith("image/"));
    const phaseLabel = status === "ai_queued" || status === "ai_image_queued" ? "Queued for AI" : "AI is repainting";
    const detailLabel = status === "ai_queued" || status === "ai_image_queued" ? "Waiting for the runner" : "Generating a review image";

    return (
        <Box
            sx={{
                border: "1px solid #d7dfef",
                borderRadius: 2,
                overflow: "hidden",
                background: "linear-gradient(135deg, rgba(255,253,249,0.96), rgba(234,242,255,0.96))",
            }}
        >
            <Stack
                direction={{ xs: "column", md: "row" }}
                sx={{
                    minHeight: { xs: 360, md: 280 },
                }}
            >
                <Box
                    sx={{
                        position: "relative",
                        flex: 1,
                        minHeight: { xs: 240, md: "auto" },
                        background: "#f8fafc",
                        overflow: "hidden",
                    }}
                >
                    {hasSourceImage && sourceFile ? (
                        <Box
                            component="img"
                            src={buildPreviewUrl(publicId, sourceFile.id)}
                            alt={sourceFile.filename}
                            sx={{
                                width: "100%",
                                height: "100%",
                                minHeight: { xs: 240, md: 280 },
                                objectFit: "cover",
                                display: "block",
                                filter: "saturate(0.82) contrast(0.96)",
                                animation: "pbn-source-breathe 2600ms ease-in-out infinite",
                            }}
                        />
                    ) : (
                        <Box sx={{ width: "100%", height: "100%", minHeight: { xs: 240, md: 280 } }} />
                    )}

                    <Box
                        sx={{
                            position: "absolute",
                            inset: 0,
                            background:
                                "linear-gradient(100deg, transparent 0%, rgba(255,255,255,0.15) 38%, rgba(255,255,255,0.72) 48%, rgba(23,72,160,0.16) 56%, transparent 72%)",
                            animation: "pbn-ai-scan 2200ms ease-in-out infinite",
                        }}
                    />

                    <Box
                        sx={{
                            position: "absolute",
                            inset: 0,
                            background:
                                "radial-gradient(circle at 18% 22%, rgba(240,93,35,0.26), transparent 18%), radial-gradient(circle at 76% 64%, rgba(23,72,160,0.22), transparent 22%)",
                            mixBlendMode: "screen",
                            animation: "pbn-colour-shift 3000ms ease-in-out infinite alternate",
                        }}
                    />
                </Box>

                <Stack
                    spacing={2}
                    justifyContent="center"
                    sx={{
                        width: { xs: "100%", md: 300 },
                        p: 2,
                        borderLeft: { xs: 0, md: "1px solid #d7dfef" },
                        borderTop: { xs: "1px solid #d7dfef", md: 0 },
                    }}
                >
                    <Stack spacing={0.5}>
                        <Typography variant="overline" color="text.secondary">
                            {phaseLabel}
                        </Typography>
                        <Typography variant="h6" sx={{ lineHeight: 1.15 }}>
                            Image exchange in progress
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                            {detailLabel}
                        </Typography>
                    </Stack>

                    <Box>
                        <LinearProgress
                            sx={{
                                height: 8,
                                borderRadius: 1,
                                backgroundColor: "rgba(23,72,160,0.12)",
                                "& .MuiLinearProgress-bar": {
                                    background: "linear-gradient(90deg, #1748a0, #f05d23)",
                                },
                            }}
                        />
                    </Box>

                    <Stack direction="row" spacing={1} aria-hidden="true">
                        {["#1748a0", "#f05d23", "#2f9e44", "#f2c94c", "#7c3aed"].map((color, index) => (
                            <Box
                                key={color}
                                sx={{
                                    width: 24,
                                    height: 24,
                                    borderRadius: 1,
                                    backgroundColor: color,
                                    boxShadow: "0 6px 18px rgba(21,32,58,0.16)",
                                    animation: `pbn-swatch-pop 1400ms ease-in-out ${index * 120}ms infinite`,
                                }}
                            />
                        ))}
                    </Stack>
                </Stack>
            </Stack>
        </Box>
    );
}
