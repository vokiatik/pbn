import { Chip } from "@mui/material";

type Props = { status: string };

const colorMap: Record<string, "default" | "success" | "warning" | "error" | "info"> = {
    uploaded: "info",
    queued: "warning",
    processing: "info",
    completed: "success",
    failed: "error",
    deleted: "default",
};

export default function StatusChip({ status }: Props) {
    return <Chip size="small" color={colorMap[status] ?? "default"} label={status} />;
}
