import { CircularProgress, LinearProgress, Paper, Stack, Typography } from "@mui/material";
import StatusChip from "../StatusChip";

type ProjectStatusPanelProps = {
    status: string;
    progress: number;
    running: boolean;
};

export function ProjectStatusPanel({ status, progress, running }: ProjectStatusPanelProps) {
    return (
        <Paper sx={{ p: 2, mb: 3 }}>
            <Stack direction="row" spacing={2} alignItems="center" mb={1}>
                <Typography>Status:</Typography>
                <StatusChip status={status} />
                {running && <CircularProgress size={18} />}
            </Stack>

            <LinearProgress variant="determinate" value={progress} sx={{ height: 10, borderRadius: 8 }} />
            <Typography mt={1} color="text.secondary">
                Progress: {progress}%
            </Typography>
        </Paper>
    );
}
