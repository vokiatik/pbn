import { Box, Button, Card, CardContent, Chip, Stack, Typography } from "@mui/material";
import { useState } from "react";
import type { PBNDifficulty, PBNOption, ProjectFile } from "../../api/client";
import { buildPreviewUrl } from "../../api/client";

type Props = {
    publicId: string;
    options: PBNOption[];
    files: ProjectFile[];
    selected?: PBNDifficulty;
    disabled?: boolean;
    onSelect: (difficulty: PBNDifficulty) => Promise<void>;
};

export function PBNDifficultyOptions({ publicId, options, files, selected, disabled, onSelect }: Props) {
    const [submitting, setSubmitting] = useState(false);
    const hardOptions = options.filter((option) => option.difficulty === "hard" && option.status === "valid");

    const submit = async () => {
        if (!hardOptions.length) return;
        setSubmitting(true);
        try {
            await onSelect("hard");
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Stack spacing={2}>
            <Box>
                <Typography variant="h6">Hard PBN preview</Typography>
                <Typography color="text.secondary">
                    Review the saved preview, then create your printable files.
                </Typography>
            </Box>
            <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
                {hardOptions.map((option) => {
                    const preview = files.find((file) => file.file_type === `ai_${option.difficulty}_template_preview`);
                    const forcedMergeCount =
                        (option.selected_forced_merge_count ?? 0) +
                        (option.palette_protected_forced_merge_count ?? 0);
                    return (
                        <Card key={option.difficulty} variant="outlined" sx={{ flex: 1 }}>
                                {preview && (
                                    <Box component="img" src={buildPreviewUrl(publicId, preview.id)} alt="Hard PBN preview" sx={{ width: "100%", height: 320, objectFit: "contain", bgcolor: "#f8fafc" }} />
                                )}
                                <CardContent>
                                    <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
                                        <Typography variant="h6">Hard</Typography>
                                        {selected === option.difficulty && <Chip size="small" color="success" label="Current" />}
                                    </Stack>
                                    <Typography>{option.region_count} regions</Typography>
                                    <Typography color="text.secondary">{option.palette_size} colours · {option.prefilled_detail_count} prefilled details</Typography>
                                    {(option.advanced_area_percent ?? 0) > 0 && (
                                        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                                            Protected detail: {((option.selected_boundary_retention ?? 0) * 100).toFixed(1)}% retained
                                            {` · ${option.selected_prefilled_detail_count ?? 0} prefilled`}
                                            {` · ${forcedMergeCount} forced merges`}
                                        </Typography>
                                    )}
                                </CardContent>
                        </Card>
                    );
                })}
            </Stack>
            <Button variant="contained" disabled={!hardOptions.length || disabled || submitting} onClick={() => void submit()}>
                {submitting ? "Creating printable files…" : "Create Hard printable files"}
            </Button>
        </Stack>
    );
}
