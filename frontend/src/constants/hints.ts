// src/constants/parameterHints.ts

export const PARAMETER_HINTS: Record<number, Record<string, string>> = {
    1: {
        points_per_side:
            "Controls how carefully SAM scans the image. Higher values find more details, but run slower and may create too many small regions.",

        pred_iou_thresh:
            "Filters masks by predicted quality. Higher values keep cleaner masks, but may remove valid objects or details.",

        stability_score_thresh:
            "Filters masks by stability. Higher values keep only more reliable shapes, but can remove small or subtle regions.",

        min_mask_region_area:
            "Removes very small mask fragments during SAM cleanup. Higher values reduce noise, but can delete small details.",

        min_area_ratio:
            "Minimum allowed object size as a part of the whole image. Higher values remove tiny regions and make the result simpler.",

        max_area_ratio:
            "Maximum allowed object size as a part of the whole image. Lower values help prevent huge background masks from being treated as objects.",

        dedupe_iou:
            "Controls duplicate mask removal. Lower values remove more overlapping masks; higher values keep more similar masks.",
    },

    2: {
        colors_per_object:
            "Controls how many simplified colors each detected object can use. Lower values make objects flatter and more cartoon-like; higher values keep more detail.",

        background_colors:
            "Controls how many simplified colors are used for the background. Lower values make the background cleaner; higher values keep more background detail.",

        min_region_area:
            "Minimum useful region size in pixels. Higher values remove more tiny color islands and skip very small objects, but can delete small details.",

        process_background:
            "When enabled, the background is also simplified. When disabled, only detected objects are smoothed and the background stays closer to the original image.",

        max_objects:
            "Maximum number of detected objects to process, starting from the largest ones. Higher values process more objects but run slower and may include noise.",
    },

    3: {
        palette_size:
            "Controls the total number of colors in the final palette. Lower values make the painting simpler; higher values keep more detail but make the template harder to paint.",
    },

    4: {
        connectivity:
            "Controls how raw regions are detected from the color label map. Strict connectivity uses only side-touching pixels. Diagonal connectivity also treats diagonal-touching pixels as connected. Border smoothing and island cleanup happen in the next steps.",
    },

    5: {
        cleanup_boundary_artifacts_enabled:
            "Enables selective cleanup of jagged color borders. This targets zipper-like edges, tiny scars, small peninsulas, and uneven coastlines without smoothing the whole image.",

        boundary_cleanup_radius:
            "Controls the size of the local area used for border cleanup. Higher values clean wider border artifacts, but can simplify important edges if set too high.",

        boundary_cleanup_iterations:
            "Controls how many times border cleanup is repeated. Higher values produce stronger cleanup, but too many passes can over-simplify the image.",

        boundary_dominance_threshold:
            "Controls how dominant a neighboring color must be before a border pixel changes. Lower values clean more aggressively; higher values are more conservative.",

        boundary_min_advantage:
            "Minimum local pixel advantage needed before a border pixel changes color. Lower values clean more aggressively; higher values preserve more original detail.",

        boundary_max_current_support_ratio:
            "Maximum allowed local support for the pixel's current color before it can be changed. Lower values only change very weak/noisy border pixels; higher values allow stronger reshaping of borders.",

        use_object_guided_cleanup:
            "Uses SAM object masks to protect important object borders while cleaning color borders mostly inside object interiors. This helps preserve silhouettes and sharp object edges.",

        object_boundary_guard_px:
            "Protects this many pixels near SAM object borders from border cleanup. Higher values preserve object silhouettes better, but may leave jagged color artifacts near object edges.",

        cleanup_background:
            "When enabled, border cleanup also runs on the background area. When disabled, only detected object interiors are cleaned.",

        connectivity:
            "Controls how border pixels are detected during cleanup. Strict mode considers side-touching pixels; diagonal mode also considers diagonal-touching pixels.",
    },

    6: {
        micro_island_cleanup_enabled:
            "Removes tiny leftover islands after border cleanup. This is useful when a few-pixel dot or isolated color fragment remains after de-zippering.",

        micro_island_min_area:
            "Maximum size, in pixels, of a tiny island that should be removed. Higher values remove larger small islands, but can erase intentional tiny details.",

        micro_island_iterations:
            "Controls how many times tiny-island cleanup is repeated. More passes can remove islands created by previous cleanup passes, but too many can remove fine details.",

        micro_island_connectivity:
            "Controls how tiny islands are detected. Strict detection is better for catching diagonal or barely-attached islands. Diagonal detection is more conservative.",

        micro_island_same_object_only:
            "When enabled, tiny islands are replaced only with labels from the same SAM object/background area. This helps prevent colors leaking across object boundaries.",

        min_region_area:
            "Minimum allowed final paint region size in pixels. Regions smaller than this are merged into a neighbor after final region creation. Higher values make the template cleaner but can remove small details.",

        split_same_color_neighbors:
            "Tries to fix neighboring regions that have the same paint number by changing the smaller region to a nearby palette color. This can reduce confusing same-color borders, but may slightly distort colors.",

        connectivity:
            "Controls how final regions are detected. Strict connectivity uses only side-touching pixels. Diagonal connectivity also treats diagonal-touching pixels as connected.",
    },

    7: {
        line_thickness:
            "Controls the thickness of black borders in the final template. Higher values make lines easier to see, but can make small regions harder to read or paint.",

        font_size:
            "Controls the size of paint numbers inside regions. Larger numbers are easier to read, but may not fit inside smaller regions.",

        min_number_area:
            "Minimum region size required before placing a number. Lower values add numbers to smaller regions; higher values keep tiny regions clean but may leave them unlabeled.",
    },

    8: {
        page_width_cm:
            "Physical page width in centimeters. For A3 portrait this is usually 29.7 cm. Changing it affects the printed page size.",

        page_height_cm:
            "Physical page height in centimeters. For A3 portrait this is usually 42.0 cm. Changing it affects the printed page size.",

        dpi:
            "Print resolution. Higher DPI gives sharper output but creates larger files and uses more memory. 300 DPI is a good print default.",

        fit_mode:
            "Controls how the template fits the page. Contain keeps the whole image but may add margins. Cover fills the page but may crop edges. Stretch fills the page but distorts proportions.",

        page_orientation:
            "Controls the orientation of the page. Portrait is taller than it is wide, while landscape is wider than it is tall.",
    },
};

export function getParameterHint(step: number, parameter: string): string | undefined {
    return PARAMETER_HINTS[step]?.[parameter];
}