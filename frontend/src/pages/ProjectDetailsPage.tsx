import { Alert, Box, Button, Stack, Typography } from "@mui/material";
import { useNavigate, useParams } from "react-router-dom";
import { deleteProject } from "../api/client";
import { PreviewPanel } from "../components/Details/PreviewPanel";
import { ProjectFilesTable } from "../components/Details/ProjectFilesTable";
import { ProjectStatusPanel } from "../components/Details/ProjectStatusPanel";
import { ProjectStepper } from "../components/Details/ProjectStepper";
import { StepRunnerPanel } from "../components/Details/StepRunnerPanel";
import { UserDownloadDialog } from "../components/Details/UserDownloadDialog";
import { useProjectDetails } from "../hooks/useProjectDetails";

export function ProjectDetailsPage() {
    const { publicId = "" } = useParams();
    const navigate = useNavigate();

    const details = useProjectDetails(publicId);

    if (!details.project) return <Typography>Loading...</Typography>;
    return (
        <Box>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
                <Typography variant="h4" fontWeight={700}>
                    Project {details.project.public_id}
                </Typography>

                <Button
                    color="error"
                    onClick={async () => {
                        await deleteProject(publicId);
                        navigate("/projects");
                    }}
                >
                    Delete Project
                </Button>
            </Stack>

            {details.error && (
                <Alert severity="error" sx={{ mb: 2 }}>
                    {details.error}
                </Alert>
            )}

            <ProjectStatusPanel
                status={details.project.status}
                progress={details.progress}
                running={details.running}
            />

            <ProjectStepper
                activeStep={details.activeStep}
                status={details.project.status}
                files={details.files}
                onSelectStep={details.selectStep}
            />

            <Stack direction={{ xs: "column", lg: "row" }} spacing={3}>
                <StepRunnerPanel
                    activeStep={details.activeStep}
                    params={details.params}
                    running={details.running}
                    onRunCurrentStep={() => void details.runCurrentStep()}
                    onSelectStep={details.selectStep}
                    setStepParam={details.setStepParam}
                />

                <PreviewPanel
                    publicId={publicId}
                    previewStep={details.previewStep}
                    previewFile={details.previewFile}
                    previewLoading={details.previewLoading}
                    previewVersion={details.previewVersion}
                    pdfSettings={details.params[8]}
                    showPdfFrame={details.previewStep === 8}
                />
            </Stack>

            <ProjectFilesTable
                publicId={publicId}
                files={details.files}
                onDownload={(fileId) => void details.handleDownload(fileId)}
            />

            <UserDownloadDialog
                open={details.userDialogOpen}
                email={details.email}
                username={details.username}
                phoneNumber={details.phoneNumber}
                needMoreData={details.needMoreData}
                onClose={() => details.setUserDialogOpen(false)}
                onSkip={details.handleSkipUserDialog}
                onContinue={() => void details.handleResolveAndContinue()}
                onSaveAndDownload={() => void details.handleCreateUserAndDownload()}
                setEmail={details.setEmail}
                setUsername={details.setUsername}
                setPhoneNumber={details.setPhoneNumber}
            />
        </Box>
    );
}
