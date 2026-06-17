import { Paper, Step, StepLabel, Stepper } from "@mui/material";
import type { ProjectFile } from "../../api/client";
import { steps } from "../../types/steps";
import type { StepId } from "../../types/types";
import { stepIsCompleted } from "../../utils/stepUtils";

type ProjectStepperProps = {
    activeStep: StepId;
    status: string;
    files: ProjectFile[];
    onSelectStep: (step: StepId) => void;
};

export function ProjectStepper({ activeStep, status, files, onSelectStep }: ProjectStepperProps) {
    return (
        <Paper sx={{ p: 2, mb: 3 }}>
            <Stepper activeStep={activeStep - 1} alternativeLabel>
                {steps.map((step) => (
                    <Step key={step.id} completed={stepIsCompleted(status, step.id, files)}>
                        <StepLabel onClick={() => onSelectStep(step.id)} sx={{ cursor: "pointer" }}>
                            {step.title}
                        </StepLabel>
                    </Step>
                ))}
            </Stepper>
        </Paper>
    );
}
