import type { ProjectFile } from "../api/client";

export type EventPayload = {
    type: string;
    project_id: string;
    status?: string;
    step?: StepId;
    value?: number;
    message?: string;
    files?: ProjectFile[];
};

export type StepParams = {
    1: {
        points_per_side: number;
        pred_iou_thresh: number;
        stability_score_thresh: number;
        min_mask_region_area: number;
        min_area_ratio: number;
        max_area_ratio: number;
        dedupe_iou: number;
    };
    2: {
        colors_per_object: number;
        background_colors: number;
        min_region_area: number;
        process_background: boolean;
        max_objects: number;
    };
    3: {
        palette_size: number;
    };

    // Step 4: raw regions only
    4: {
        // 1 = strict 4-way connection, 2 = diagonal-aware 8-way connection
        connectivity: 1 | 2;
    };

    // Step 5: border cleanup / de-zippering
    5: {
        cleanup_boundary_artifacts_enabled: boolean;
        boundary_cleanup_radius: number;
        boundary_cleanup_iterations: number;
        boundary_dominance_threshold: number;
        boundary_min_advantage: number;
        boundary_max_current_support_ratio: number;

        use_object_guided_cleanup: boolean;
        object_boundary_guard_px: number;
        cleanup_background: boolean;

        // 1 = strict 4-way connection, 2 = diagonal-aware 8-way connection
        connectivity: 1 | 2;
    };

    // Step 6: micro-island cleanup + final region map
    6: {
        micro_island_cleanup_enabled: boolean;
        micro_island_min_area: number;
        micro_island_iterations: number;
        micro_island_connectivity: 1 | 2;
        micro_island_same_object_only: boolean;

        min_region_area: number;
        split_same_color_neighbors: boolean;

        // 1 = strict 4-way connection, 2 = diagonal-aware 8-way connection
        connectivity: 1 | 2;
    };

    // Step 7: template
    7: {
        line_thickness: number;
        font_size: number;
        min_number_area: number;
    };

    // Step 8: PDF export
    8: {
        page_width_cm: number;
        page_height_cm: number;
        dpi: number;
        fit_mode: "cover" | "contain" | "stretch";
    };
};

export type StepId = keyof StepParams;

export type StepMeta = {
    id: StepId;
    title: string;
    previewTypes: string[];
    fileTypes: string[];
};

export type SetStepParam = <TStep extends StepId, TKey extends keyof StepParams[TStep]>(
    step: TStep,
    key: TKey,
    value: StepParams[TStep][TKey]
) => void;
