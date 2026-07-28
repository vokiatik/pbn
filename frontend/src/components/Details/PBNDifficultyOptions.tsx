import { Box, Button, Card, CardActionArea, CardContent, Chip, Stack, Typography } from "@mui/material";
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

const labels: Record<PBNDifficulty, string> = { easy: "Easy", medium: "Medium", hard: "Hard" };

export function PBNDifficultyOptions({ publicId, options, files, selected, disabled, onSelect }: Props) {
    const [choice, setChoice] = useState<PBNDifficulty | null>(null);
    const [submitting, setSubmitting] = useState(false);

    const submit = async () => {
        if (!choice) return;
        setSubmitting(true);
        try {
            await onSelect(choice);
            setChoice(null);
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Stack spacing={2}>
            <Box>
                <Typography variant="h6">Choose painting difficulty</Typography>
                <Typography color="text.secondary">
                    These versions are saved. You can change your selection later without regenerating the AI image.
                </Typography>
            </Box>
            <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
                {options.map((option) => {
                    const preview = files.find((file) => file.file_type === `ai_${option.difficulty}_template_preview`);
                    const active = choice === option.difficulty;
                    const forcedMergeCount =
                        (option.selected_forced_merge_count ?? 0) +
                        (option.palette_protected_forced_merge_count ?? 0);
                    return (
                        <Card key={option.difficulty} variant="outlined" sx={{ flex: 1, borderColor: active ? "primary.main" : undefined, borderWidth: active ? 2 : 1 }}>
                            <CardActionArea disabled={disabled || submitting} onClick={() => setChoice(option.difficulty)}>
                                {preview && (
                                    <Box component="img" src={buildPreviewUrl(publicId, preview.id)} alt={`${labels[option.difficulty]} PBN preview`} sx={{ width: "100%", height: 220, objectFit: "contain", bgcolor: "#f8fafc" }} />
                                )}
                                <CardContent>
                                    <Stack direction="row" justifyContent="space-between" alignItems="center" mb={1}>
                                        <Typography variant="h6">{labels[option.difficulty]}</Typography>
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
                            </CardActionArea>
                        </Card>
                    );
                })}
            </Stack>
            <Button variant="contained" disabled={!choice || disabled || submitting} onClick={() => void submit()}>
                {submitting ? "Creating printable files…" : choice ? `Create ${labels[choice]} printable files` : "Select a difficulty"}
            </Button>
        </Stack>
    );
}
