import {
    Box,
    Button,
    CircularProgress,
    Paper,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { deleteProject, listProjects, Project } from "../api/client";
import StatusChip from "../components/StatusChip";

function getProjectPhase(status: string): string {
    if (status === "uploaded") return "Uploaded";
    if (status === "completed") return "Completed";
    if (status === "failed") return "Failed";

    const match = status.match(/^step_(\d+)_(queued|processing|completed|failed)$/);

    if (!match) return status;

    const step = match[1];
    const phase = match[2];

    return `Step ${step} ${phase}`;
}

export default function RequestsListPage() {
    const [items, setItems] = useState<Project[]>([]);
    const [loading, setLoading] = useState(true);
    const [page, setPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);

    const load = async (targetPage: number) => {
        setLoading(true);

        try {
            const data = await listProjects(targetPage, 10);

            setItems(data.items);
            setTotalPages(data.total_pages || 1);
            setPage(targetPage);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        void load(1);
    }, []);

    return (
        <Box>
            <Typography variant="h4" fontWeight={700} gutterBottom>
                Projects
            </Typography>

            <Paper sx={{ overflowX: "auto", minWidth: 0, width: "100%" }}>
                {loading ? (
                    <Stack alignItems="center" py={5}>
                        <CircularProgress />
                    </Stack>
                ) : (
                    <Table
                        sx={{
                            width: "100%",
                            tableLayout: "fixed",
                            "& .MuiTableCell-root": {
                                whiteSpace: "normal",
                                overflowWrap: "anywhere",
                                wordBreak: "break-word",
                                verticalAlign: "top",
                            },
                        }}
                    >
                        <TableHead>
                            <TableRow>
                                <TableCell>Project ID</TableCell>
                                <TableCell>User</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell>Pipeline</TableCell>
                                <TableCell>Upload Date</TableCell>
                                <TableCell>Completion Date</TableCell>
                                <TableCell>Files</TableCell>
                                <TableCell>Original</TableCell>
                                <TableCell align="right">Actions</TableCell>
                            </TableRow>
                        </TableHead>

                        <TableBody>
                            {items.map((project) => (
                                <TableRow key={project.id} hover>
                                    <TableCell>{project.public_id}</TableCell>
                                    <TableCell>{project.username || "-"}</TableCell>

                                    <TableCell>
                                        <StatusChip status={project.status} />
                                    </TableCell>

                                    <TableCell>{getProjectPhase(project.status)}</TableCell>

                                    <TableCell>
                                        {new Date(project.created_at).toLocaleString()}
                                    </TableCell>

                                    <TableCell>
                                        {project.completed_at
                                            ? new Date(project.completed_at).toLocaleString()
                                            : "-"}
                                    </TableCell>

                                    <TableCell>{project.files_count}</TableCell>
                                    <TableCell>{project.original_filename}</TableCell>

                                    <TableCell align="right">
                                        <Stack
                                            direction={{ xs: "column", sm: "row" }}
                                            spacing={1}
                                            justifyContent="flex-end"
                                            alignItems="flex-end"
                                        >
                                            <Button
                                                component={Link}
                                                to={`/projects/${project.public_id}`}
                                                size="small"
                                                variant="outlined"
                                            >
                                                Open
                                            </Button>

                                            <Button
                                                size="small"
                                                color="error"
                                                onClick={async () => {
                                                    await deleteProject(project.public_id);
                                                    await load(page);
                                                }}
                                            >
                                                Delete
                                            </Button>
                                        </Stack>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
            </Paper>

            <Stack direction="row" spacing={1} mt={2} justifyContent="flex-end">
                <Button disabled={page <= 1} onClick={() => void load(page - 1)}>
                    Prev
                </Button>

                <Typography sx={{ alignSelf: "center" }}>
                    {page} / {totalPages}
                </Typography>

                <Button disabled={page >= totalPages} onClick={() => void load(page + 1)}>
                    Next
                </Button>
            </Stack>
        </Box>
    );
}