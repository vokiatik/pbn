import type { StepMeta, StepParams } from "./types";

export const MIN_STEP = 1;
export const MAX_STEP = 8;
export const STEP_IDS = [1, 2, 3, 4, 5, 6, 7, 8] as const;

export const defaultParams: StepParams = {
    1: {
        points_per_side: 32,
        pred_iou_thresh: 0.88,
        stability_score_thresh: 0.92,
        min_mask_region_area: 400,
        min_area_ratio: 0.002,
        max_area_ratio: 0.8,
        dedupe_iou: 0.92,
    },
    2: {
        colors_per_object: 5,
        background_colors: 6,
        min_region_area: 300,
        process_background: true,
        max_objects: 80,
    },
    3: {
        palette_size: 30,
    },
    4: {
        // Raw region creation only
        connectivity: 2,
    },
    5: {
        // Border cleanup / de-zippering
        cleanup_boundary_artifacts_enabled: true,
        boundary_cleanup_radius: 3,
        boundary_cleanup_iterations: 3,
        boundary_dominance_threshold: 0.58,
        boundary_min_advantage: 2,
        boundary_max_current_support_ratio: 0.45,

        use_object_guided_cleanup: true,
        object_boundary_guard_px: 4,
        cleanup_background: true,

        connectivity: 2,
    },
    6: {
        // Island cleanup + final region map
        micro_island_cleanup_enabled: true,
        micro_island_min_area: 80,
        micro_island_iterations: 4,
        micro_island_connectivity: 1,
        micro_island_same_object_only: true,

        min_region_area: 700,
        split_same_color_neighbors: false,

        connectivity: 2,
    },
    7: {
        line_thickness: 1,
        font_size: 14,
        min_number_area: 100,
    },
    8: {
        page_width_cm: 29.7,
        page_height_cm: 42,
        dpi: 300,
        fit_mode: "cover",
    },
};

export const steps: StepMeta[] = [
    {
        id: 1,
        title: "Object masks",
        previewTypes: ["step1_overlay"],
        fileTypes: ["step1_overlay"],
    },
    {
        id: 2,
        title: "Smooth objects",
        previewTypes: ["step2_smoothed"],
        fileTypes: ["step2_smoothed"],
    },
    {
        id: 3,
        title: "Global palette",
        previewTypes: ["step3_palette_image", "step3_palette_preview"],
        fileTypes: ["step3_palette_image", "step3_palette_preview"],
    },
    {
        id: 4,
        title: "Raw regions",
        previewTypes: ["step4_raw_region_color_image"],
        fileTypes: ["step4_raw_region_color_image"],
    },
    {
        id: 5,
        title: "Border smoothing",
        previewTypes: ["step5_border_cleaned_preview"],
        fileTypes: ["step5_border_cleaned_preview"],
    },
    {
        id: 6,
        title: "Islands cleanup",
        previewTypes: ["step6_final_region_color_image"],
        fileTypes: ["step6_final_region_color_image"],
    },
    {
        id: 7,
        title: "Template",
        previewTypes: ["step7_pbn_template"],
        fileTypes: ["step7_pbn_template", "step7_palette_sheet"],
    },
    {
        id: 8,
        title: "PDF export",
        previewTypes: ["pbn_final", "step8_pbn_template_A3_preview"],
        fileTypes: ["pbn_final", "pbn_final_palette"],
    },
];
