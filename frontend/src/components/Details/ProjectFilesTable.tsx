import { Button, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import type { ProjectFile } from "../../api/client";
import { buildPreviewUrl } from "../../api/client";
import { steps } from "../../types/steps";

type ProjectFilesTableProps = {
    publicId: string;
    files: ProjectFile[];
    onDownload: (fileId: string) => void;
};

export function ProjectFilesTable({ publicId, files, onDownload }: ProjectFilesTableProps) {
    const visibleTypes = new Set(["upload_preview", ...steps.flatMap((step) => step.fileTypes)]);
    const sortedFiles = files
        .filter((file) => visibleTypes.has(file.file_type))
        .sort((a, b) => a.filename.localeCompare(b.filename));

    return (
        <Paper sx={{ p: 2, mt: 3 }}>
            <Typography variant="h6" mb={2}>Files</Typography>

            <Table size="small">
                <TableHead>
                    <TableRow>
                        <TableCell>Type</TableCell>
                        <TableCell>Name</TableCell>
                        <TableCell>Size</TableCell>
                        <TableCell align="right">Actions</TableCell>
                    </TableRow>
                </TableHead>

                <TableBody>
                    {sortedFiles.map((file) => (
                        <TableRow key={file.id}>
                            <TableCell>{file.file_type}</TableCell>
                            <TableCell>{file.filename}</TableCell>
                            <TableCell>{(file.size_bytes / 1024).toFixed(1)} KB</TableCell>
                            <TableCell align="right">
                                <Stack direction="row" spacing={1} justifyContent="flex-end">
                                    <Button size="small" onClick={() => window.open(buildPreviewUrl(publicId, file.id), "_blank")}>
                                        Preview
                                    </Button>
                                    <Button size="small" variant="contained" onClick={() => onDownload(file.id)}>
                                        Download
                                    </Button>
                                </Stack>
                            </TableCell>
                        </TableRow>
                    ))}
                </TableBody>
            </Table>
        </Paper>
    );
}
