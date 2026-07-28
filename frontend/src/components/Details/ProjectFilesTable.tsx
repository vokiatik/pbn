import { Button, Paper, Stack, Table, TableBody, TableCell, TableHead, TableRow, Typography } from "@mui/material";
import type { ProjectFile } from "../../api/client";
import { buildPreviewUrl } from "../../api/client";

type ProjectFilesTableProps = {
    publicId: string;
    files: ProjectFile[];
    onDownload: (fileId: string) => void;
};

type DisplayFileDefinition = {
    displayName: string;
    downloadTypes: string[];
    previewTypes?: string[];
};

type DisplayFile = DisplayFileDefinition & {
    downloadFile: ProjectFile;
    previewFile: ProjectFile;
};

const displayFileDefinitions: DisplayFileDefinition[] = [
    {
        displayName: "Original image",
        downloadTypes: ["original", "original_upload"],
        previewTypes: ["upload_preview", "original", "original_upload"],
    },
    {
        displayName: "AI-generated image",
        downloadTypes: ["ai_simplified"],
    },
    {
        displayName: "Coloured preview",
        downloadTypes: ["ai_painted_reference"],
    },
    {
        displayName: "Paint-by-number preview",
        downloadTypes: ["ai_final"],
    },
    {
        displayName: "Final PBN template",
        downloadTypes: ["ai_template_pdf"],
    },
    {
        displayName: "Colour palette",
        downloadTypes: ["ai_palette_pdf", "ai_final_palette", "ai_palette_sheet"],
        previewTypes: ["ai_final_palette", "ai_palette_sheet", "ai_palette_pdf"],
    },
];

function findFileByType(files: ProjectFile[], fileTypes: string[]): ProjectFile | undefined {
    return fileTypes
        .map((fileType) => files.find((file) => file.file_type === fileType))
        .find((file): file is ProjectFile => Boolean(file));
}

function getDisplayFilename(displayName: string, file: ProjectFile): string {
    const extensionStart = file.filename.lastIndexOf(".");
    const extension = extensionStart >= 0 ? file.filename.slice(extensionStart).toLowerCase() : "";
    return `${displayName}${extension}`;
}

export function ProjectFilesTable({ publicId, files, onDownload }: ProjectFilesTableProps) {
    const displayFiles = displayFileDefinitions
        .map((definition): DisplayFile | null => {
            const downloadFile = findFileByType(files, definition.downloadTypes);
            if (!downloadFile) return null;

            const previewFile = findFileByType(
                files,
                definition.previewTypes ?? definition.downloadTypes,
            ) ?? downloadFile;

            return { ...definition, downloadFile, previewFile };
        })
        .filter((file): file is DisplayFile => Boolean(file));

    return (
        <Paper sx={{ p: 2, mt: 3 }}>
            <Typography variant="h6" mb={2}>Files</Typography>

            <Table size="small">
                <TableHead>
                    <TableRow>
                        <TableCell>Name</TableCell>
                        <TableCell>Size</TableCell>
                        <TableCell align="right">Actions</TableCell>
                    </TableRow>
                </TableHead>

                <TableBody>
                    {displayFiles.map(({ displayName, downloadFile, previewFile }) => (
                        <TableRow key={displayName}>
                            <TableCell>{getDisplayFilename(displayName, downloadFile)}</TableCell>
                            <TableCell>{(downloadFile.size_bytes / 1024).toFixed(1)} KB</TableCell>
                            <TableCell align="right">
                                <Stack direction="row" spacing={1} justifyContent="flex-end">
                                    <Button size="small" onClick={() => window.open(buildPreviewUrl(publicId, previewFile.id), "_blank")}>
                                        Preview
                                    </Button>
                                    <Button size="small" variant="contained" onClick={() => onDownload(downloadFile.id)}>
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
