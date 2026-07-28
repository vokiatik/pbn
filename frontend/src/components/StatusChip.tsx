import { Chip } from "@mui/material";

type Props = { status: string };

const colorMap: Record<string, "default" | "success" | "warning" | "error" | "info"> = {
    uploaded: "info",
    upload_preview_processing: "info",
    upload_preview_queued: "warning",
    queued: "warning",
    processing: "info",
    completed: "success",
    failed: "error",
    ai_queued: "warning",
    ai_processing: "info",
    ai_image_queued: "warning",
    ai_image_processing: "info",
    ai_image_ready: "success",
    pbn_queued: "warning",
    pbn_processing: "info",
    pbn_options_queued: "warning",
    pbn_options_processing: "info",
    pbn_options_ready: "success",
    pbn_selection_queued: "warning",
    pbn_selection_processing: "info",
    pbn_selection_failed: "error",
    pbn_failed: "error",
    ai_completed: "success",
    ai_failed: "error",
    deleted: "default",
};

export default function StatusChip({ status }: Props) {
    return <Chip size="small" color={colorMap[status] ?? "default"} label={status} />;
}
