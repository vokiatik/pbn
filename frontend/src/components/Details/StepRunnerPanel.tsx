import { Button, Chip, Divider, Paper, Stack, Typography } from "@mui/material";
import { MAX_STEP, MIN_STEP, steps } from "../../types/steps";
import type { SetStepParam, StepId, StepParams } from "../../types/types";
import { clampStep } from "../../utils/stepUtils";
import { StepParamsForm } from "./StepParamsForm";

type StepRunnerPanelProps = {
    activeStep: StepId;
    params: StepParams;
    running: boolean;
    onRunCurrentStep: () => void;
    onSelectStep: (step: StepId) => void;
    setStepParam: SetStepParam;
};

export function StepRunnerPanel({
    activeStep,
    params,
    running,
    onRunCurrentStep,
    onSelectStep,
    setStepParam,
}: StepRunnerPanelProps) {
    const stepTitle = steps.find((step) => step.id === activeStep)?.title;

    return (
        <Paper sx={{ p: 2, flex: 1 }}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" mb={2}>
                <BoxTitle activeStep={activeStep} stepTitle={stepTitle} />
                <Chip label={`Run Step ${activeStep}`} />
            </Stack>

            <Divider sx={{ mb: 2 }} />

            <Stack spacing={2}>
                <StepParamsForm activeStep={activeStep} params={params} setStepParam={setStepParam} />

                <Button variant="contained" onClick={onRunCurrentStep} disabled={running}>
                    {running ? "Running..." : `Run Step ${activeStep}`}
                </Button>

                <Stack direction="row" spacing={1}>
                    <Button disabled={activeStep === MIN_STEP} onClick={() => onSelectStep(clampStep(activeStep - 1))}>
                        Previous
                    </Button>
                    <Button disabled={activeStep === MAX_STEP} onClick={() => onSelectStep(clampStep(activeStep + 1))}>
                        Next
                    </Button>
                </Stack>
            </Stack>
        </Paper>
    );
}

function BoxTitle({ activeStep, stepTitle }: { activeStep: StepId; stepTitle?: string }) {
    return (
        <div>
            <Typography variant="h6">
                Step {activeStep}: {stepTitle}
            </Typography>

            <Typography color="text.secondary" variant="body2">
                Tune parameters, run this step, inspect preview, then continue.
            </Typography>
        </div>
    );
}
