import { Box, Button, CircularProgress, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { deleteProject, listProjects, Project } from "../api/client";
import StatusChip from "../components/StatusChip";

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
                Requests
            </Typography>
            <Paper sx={{ overflow: "hidden" }}>
                {loading ? (
                    <Stack alignItems="center" py={5}>
                        <CircularProgress />
                    </Stack>
                ) : (
                    <Table>
                        <TableHead>
                            <TableRow>
                                <TableCell>Project ID</TableCell>
                                <TableCell>Username</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell>Upload Date</TableCell>
                                <TableCell>Completion Date</TableCell>
                                <TableCell>Generated Files</TableCell>
                                <TableCell>Original File</TableCell>
                                <TableCell align="right">Actions</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {items.map((p) => (
                                <TableRow key={p.id} hover>
                                    <TableCell>{p.public_id}</TableCell>
                                    <TableCell>{p.username || "-"}</TableCell>
                                    <TableCell><StatusChip status={p.status} /></TableCell>
                                    <TableCell>{new Date(p.created_at).toLocaleString()}</TableCell>
                                    <TableCell>{p.completed_at ? new Date(p.completed_at).toLocaleString() : "-"}</TableCell>
                                    <TableCell>{p.files_count}</TableCell>
                                    <TableCell>{p.original_filename}</TableCell>
                                    <TableCell align="right">
                                        <Stack direction="row" spacing={1} justifyContent="flex-end">
                                            <Button component={Link} to={`/projects/${p.public_id}`} size="small" variant="outlined">Open</Button>
                                            <Button
                                                size="small"
                                                color="error"
                                                onClick={async () => {
                                                    await deleteProject(p.public_id);
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
                <Button disabled={page <= 1} onClick={() => void load(page - 1)}>Prev</Button>
                <Typography sx={{ alignSelf: "center" }}>{page} / {totalPages}</Typography>
                <Button disabled={page >= totalPages} onClick={() => void load(page + 1)}>Next</Button>
            </Stack>
        </Box>
    );
}
