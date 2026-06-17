import { Button, FormControlLabel, Stack, Switch } from "@mui/material";
import { NumberField } from "./NumberField";
import type { SetStepParam, StepId, StepParams } from "../../types/types";
import { FieldWithHint } from "../FieldWithHint";
import { getParameterHint } from "../../constants/hints";

type StepParamsFormProps = {
    activeStep: StepId;
    params: StepParams;
    setStepParam: SetStepParam;
};

export function StepParamsForm({ activeStep, params, setStepParam }: StepParamsFormProps) {
    const isClose = (a: number, b: number) => Math.abs(a - b) < 0.01;

    const isA3Portrait =
        isClose(params[8].page_width_cm, 29.7) &&
        isClose(params[8].page_height_cm, 42);

    const isA3Landscape =
        isClose(params[8].page_width_cm, 42) &&
        isClose(params[8].page_height_cm, 29.7);

    return (
        <>
            {activeStep === 1 && (
                <>
                    <FieldWithHint hint={getParameterHint(1, "points_per_side")}>
                        <NumberField
                            label="points_per_side"
                            value={params[1].points_per_side}
                            onChange={(v) => setStepParam(1, "points_per_side", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(1, "pred_iou_thresh")}>
                        <NumberField
                            label="pred_iou_thresh"
                            value={params[1].pred_iou_thresh}
                            step={0.01}
                            min={0}
                            max={1}
                            onChange={(v) => setStepParam(1, "pred_iou_thresh", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(1, "stability_score_thresh")}>
                        <NumberField
                            label="stability_score_thresh"
                            value={params[1].stability_score_thresh}
                            step={0.01}
                            min={0}
                            max={1}
                            onChange={(v) => setStepParam(1, "stability_score_thresh", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(1, "min_mask_region_area")}>
                        <NumberField
                            label="min_mask_region_area"
                            value={params[1].min_mask_region_area}
                            onChange={(v) => setStepParam(1, "min_mask_region_area", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(1, "min_area_ratio")}>
                        <NumberField
                            label="min_area_ratio"
                            value={params[1].min_area_ratio}
                            step={0.001}
                            min={0}
                            max={1}
                            onChange={(v) => setStepParam(1, "min_area_ratio", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(1, "max_area_ratio")}>
                        <NumberField
                            label="max_area_ratio"
                            value={params[1].max_area_ratio}
                            step={0.01}
                            min={0}
                            max={1}
                            onChange={(v) => setStepParam(1, "max_area_ratio", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(1, "dedupe_iou")}>
                        <NumberField
                            label="dedupe_iou"
                            value={params[1].dedupe_iou}
                            step={0.01}
                            min={0}
                            max={1}
                            onChange={(v) => setStepParam(1, "dedupe_iou", v)}
                        />
                    </FieldWithHint>
                </>
            )}

            {activeStep === 2 && (
                <>
                    <FieldWithHint hint={getParameterHint(2, "colors_per_object")}>
                        <NumberField
                            label="Object color detail"
                            value={params[2].colors_per_object}
                            min={1}
                            onChange={(v) => setStepParam(2, "colors_per_object", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(2, "background_colors")}>
                        <NumberField
                            label="Background color detail"
                            value={params[2].background_colors}
                            min={1}
                            onChange={(v) => setStepParam(2, "background_colors", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(2, "min_region_area")}>
                        <NumberField
                            label="Small region cleanup"
                            value={params[2].min_region_area}
                            min={0}
                            onChange={(v) => setStepParam(2, "min_region_area", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(2, "process_background")}>
                        <FormControlLabel
                            control={
                                <Switch
                                    checked={params[2].process_background}
                                    onChange={(e) =>
                                        setStepParam(2, "process_background", e.target.checked)
                                    }
                                />
                            }
                            label="Smooth background"
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(2, "max_objects")}>
                        <NumberField
                            label="Objects to process"
                            value={params[2].max_objects}
                            min={1}
                            onChange={(v) => setStepParam(2, "max_objects", v)}
                        />
                    </FieldWithHint>
                </>
            )}

            {activeStep === 3 && (
                <FieldWithHint hint={getParameterHint(3, "palette_size")}>
                    <NumberField
                        label="Number of paint colors"
                        value={params[3].palette_size}
                        min={8}
                        max={60}
                        onChange={(v) => setStepParam(3, "palette_size", v)}
                    />
                </FieldWithHint>
            )}

            {activeStep === 4 && (
                <>
                    <FieldWithHint hint={getParameterHint(4, "connectivity")}>
                        <Stack direction="row" spacing={1}>
                            <Button
                                size="small"
                                variant={params[4].connectivity === 1 ? "contained" : "outlined"}
                                onClick={() => setStepParam(4, "connectivity", 1)}
                            >
                                Strict region connection mode
                            </Button>

                            <Button
                                size="small"
                                variant={params[4].connectivity === 2 ? "contained" : "outlined"}
                                onClick={() => setStepParam(4, "connectivity", 2)}
                            >
                                Diagonal region connection mode
                            </Button>
                        </Stack>
                    </FieldWithHint>
                </>
            )}

            {activeStep === 5 && (
                <>
                    <FieldWithHint hint={getParameterHint(5, "cleanup_boundary_artifacts_enabled")}>
                        <FormControlLabel
                            control={
                                <Switch
                                    checked={params[5].cleanup_boundary_artifacts_enabled}
                                    onChange={(e) =>
                                        setStepParam(
                                            5,
                                            "cleanup_boundary_artifacts_enabled",
                                            e.target.checked
                                        )
                                    }
                                />
                            }
                            label="Clean zipper-like borders"
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(5, "boundary_cleanup_radius")}>
                        <NumberField
                            label="Border cleanup radius"
                            value={params[5].boundary_cleanup_radius}
                            min={1}
                            max={10}
                            onChange={(v) => setStepParam(5, "boundary_cleanup_radius", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(5, "boundary_cleanup_iterations")}>
                        <NumberField
                            label="Border cleanup passes"
                            value={params[5].boundary_cleanup_iterations}
                            min={1}
                            max={10}
                            onChange={(v) => setStepParam(5, "boundary_cleanup_iterations", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(5, "boundary_dominance_threshold")}>
                        <NumberField
                            label="Border dominance threshold"
                            value={params[5].boundary_dominance_threshold}
                            step={0.01}
                            min={0.5}
                            max={0.9}
                            onChange={(v) => setStepParam(5, "boundary_dominance_threshold", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(5, "boundary_min_advantage")}>
                        <NumberField
                            label="Border change confidence"
                            value={params[5].boundary_min_advantage}
                            min={1}
                            max={20}
                            onChange={(v) => setStepParam(5, "boundary_min_advantage", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(5, "boundary_max_current_support_ratio")}>
                        <NumberField
                            label="Weak current-label limit"
                            value={params[5].boundary_max_current_support_ratio}
                            step={0.01}
                            min={0.1}
                            max={0.8}
                            onChange={(v) =>
                                setStepParam(5, "boundary_max_current_support_ratio", v)
                            }
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(5, "use_object_guided_cleanup")}>
                        <FormControlLabel
                            control={
                                <Switch
                                    checked={params[5].use_object_guided_cleanup}
                                    onChange={(e) =>
                                        setStepParam(5, "use_object_guided_cleanup", e.target.checked)
                                    }
                                />
                            }
                            label="Protect SAM object borders"
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(5, "object_boundary_guard_px")}>
                        <NumberField
                            label="Object border protection"
                            value={params[5].object_boundary_guard_px}
                            min={0}
                            max={30}
                            onChange={(v) => setStepParam(5, "object_boundary_guard_px", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(5, "cleanup_background")}>
                        <FormControlLabel
                            control={
                                <Switch
                                    checked={params[5].cleanup_background}
                                    onChange={(e) =>
                                        setStepParam(5, "cleanup_background", e.target.checked)
                                    }
                                />
                            }
                            label="Clean background too"
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(5, "connectivity")}>
                        <Stack direction="row" spacing={1}>
                            <Button
                                size="small"
                                variant={params[5].connectivity === 1 ? "contained" : "outlined"}
                                onClick={() => setStepParam(5, "connectivity", 1)}
                            >
                                Strict cleanup connectivity
                            </Button>

                            <Button
                                size="small"
                                variant={params[5].connectivity === 2 ? "contained" : "outlined"}
                                onClick={() => setStepParam(5, "connectivity", 2)}
                            >
                                Diagonal cleanup connectivity
                            </Button>
                        </Stack>
                    </FieldWithHint>
                </>
            )}

            {activeStep === 6 && (
                <>
                    <FieldWithHint hint={getParameterHint(6, "micro_island_cleanup_enabled")}>
                        <FormControlLabel
                            control={
                                <Switch
                                    checked={params[6].micro_island_cleanup_enabled}
                                    onChange={(e) =>
                                        setStepParam(
                                            6,
                                            "micro_island_cleanup_enabled",
                                            e.target.checked
                                        )
                                    }
                                />
                            }
                            label="Remove tiny leftover islands"
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(6, "micro_island_min_area")}>
                        <NumberField
                            label="Tiny island maximum size"
                            value={params[6].micro_island_min_area}
                            min={1}
                            max={1000}
                            onChange={(v) => setStepParam(6, "micro_island_min_area", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(6, "micro_island_iterations")}>
                        <NumberField
                            label="Tiny island cleanup passes"
                            value={params[6].micro_island_iterations}
                            min={1}
                            max={10}
                            onChange={(v) => setStepParam(6, "micro_island_iterations", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(6, "micro_island_connectivity")}>
                        <Stack direction="row" spacing={1}>
                            <Button
                                size="small"
                                variant={
                                    params[6].micro_island_connectivity === 1
                                        ? "contained"
                                        : "outlined"
                                }
                                onClick={() => setStepParam(6, "micro_island_connectivity", 1)}
                            >
                                Strict island detection
                            </Button>

                            <Button
                                size="small"
                                variant={
                                    params[6].micro_island_connectivity === 2
                                        ? "contained"
                                        : "outlined"
                                }
                                onClick={() => setStepParam(6, "micro_island_connectivity", 2)}
                            >
                                Diagonal island detection
                            </Button>
                        </Stack>
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(6, "micro_island_same_object_only")}>
                        <FormControlLabel
                            control={
                                <Switch
                                    checked={params[6].micro_island_same_object_only}
                                    onChange={(e) =>
                                        setStepParam(
                                            6,
                                            "micro_island_same_object_only",
                                            e.target.checked
                                        )
                                    }
                                />
                            }
                            label="Keep island cleanup inside same object"
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(6, "min_region_area")}>
                        <NumberField
                            label="Minimum final paint region size"
                            value={params[6].min_region_area}
                            min={0}
                            max={5000}
                            onChange={(v) => setStepParam(6, "min_region_area", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(6, "split_same_color_neighbors")}>
                        <FormControlLabel
                            control={
                                <Switch
                                    checked={params[6].split_same_color_neighbors}
                                    onChange={(e) =>
                                        setStepParam(6, "split_same_color_neighbors", e.target.checked)
                                    }
                                />
                            }
                            label="Split same-color touching neighbors"
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(6, "connectivity")}>
                        <Stack direction="row" spacing={1}>
                            <Button
                                size="small"
                                variant={params[6].connectivity === 1 ? "contained" : "outlined"}
                                onClick={() => setStepParam(6, "connectivity", 1)}
                            >
                                Strict final region connectivity
                            </Button>

                            <Button
                                size="small"
                                variant={params[6].connectivity === 2 ? "contained" : "outlined"}
                                onClick={() => setStepParam(6, "connectivity", 2)}
                            >
                                Diagonal final region connectivity
                            </Button>
                        </Stack>
                    </FieldWithHint>
                </>
            )}

            {activeStep === 7 && (
                <>
                    <FieldWithHint hint={getParameterHint(7, "line_thickness")}>
                        <NumberField
                            label="Outline thickness"
                            value={params[7].line_thickness}
                            min={1}
                            max={10}
                            onChange={(v) => setStepParam(7, "line_thickness", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(7, "font_size")}>
                        <NumberField
                            label="Number size"
                            value={params[7].font_size}
                            min={6}
                            max={48}
                            onChange={(v) => setStepParam(7, "font_size", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(7, "min_number_area")}>
                        <NumberField
                            label="Minimum area for numbers"
                            value={params[7].min_number_area}
                            min={0}
                            onChange={(v) => setStepParam(7, "min_number_area", v)}
                        />
                    </FieldWithHint>
                </>
            )}

            {activeStep === 8 && (
                <>
                    <FieldWithHint hint={getParameterHint(8, "page_width_cm")}>
                        <NumberField
                            label="Page width (cm)"
                            value={params[8].page_width_cm}
                            step={0.1}
                            min={1}
                            onChange={(v) => setStepParam(8, "page_width_cm", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(8, "page_height_cm")}>
                        <NumberField
                            label="Page height (cm)"
                            value={params[8].page_height_cm}
                            step={0.1}
                            min={1}
                            onChange={(v) => setStepParam(8, "page_height_cm", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(8, "dpi")}>
                        <NumberField
                            label="DPI"
                            value={params[8].dpi}
                            min={72}
                            max={600}
                            onChange={(v) => setStepParam(8, "dpi", v)}
                        />
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(8, "page_width_cm")}>
                        <Stack direction="row" spacing={1}>
                            <Button
                                size="small"
                                variant={isA3Portrait ? "contained" : "outlined"}
                                onClick={() => {
                                    setStepParam(8, "page_width_cm", 29.7);
                                    setStepParam(8, "page_height_cm", 42);
                                }}
                            >
                                A3 Portrait
                            </Button>

                            <Button
                                size="small"
                                variant={isA3Landscape ? "contained" : "outlined"}
                                onClick={() => {
                                    setStepParam(8, "page_width_cm", 42);
                                    setStepParam(8, "page_height_cm", 29.7);
                                }}
                            >
                                A3 Landscape
                            </Button>
                        </Stack>
                    </FieldWithHint>

                    <FieldWithHint hint={getParameterHint(8, "fit_mode")}>
                        <Stack direction="row" spacing={1}>
                            <Button
                                size="small"
                                variant={params[8].fit_mode === "contain" ? "contained" : "outlined"}
                                onClick={() => setStepParam(8, "fit_mode", "contain")}
                            >
                                Contain
                            </Button>

                            <Button
                                size="small"
                                variant={params[8].fit_mode === "cover" ? "contained" : "outlined"}
                                onClick={() => setStepParam(8, "fit_mode", "cover")}
                            >
                                Cover
                            </Button>

                            <Button
                                size="small"
                                variant={params[8].fit_mode === "stretch" ? "contained" : "outlined"}
                                onClick={() => setStepParam(8, "fit_mode", "stretch")}
                            >
                                Stretch
                            </Button>
                        </Stack>
                    </FieldWithHint>
                </>
            )}
        </>
    );
}