from __future__ import annotations

STEP_PROGRESS = {
    1: 12,
    2: 25,
    3: 38,
    4: 50,
    5: 62,
    6: 75,
    7: 88,
    8: 100,
}

# These file_type values should match the frontend preview config.
# The paths are intentionally optional: missing files are simply skipped.
PUBLIC_STEP_FILES = {
    1: [
        ("step1_overlay", "step1_objects/overlay.png"),
    ],
    2: [
        ("step2_smoothed", "step2_smooth/step2_smoothed.png"),
    ],
    3: [
        ("step3_palette_image", "step3_palette/step3_palette_image.png"),
        ("step3_palette_preview", "step3_palette/palette_preview.png"),
    ],
    4: [
        ("step4_raw_region_color_image", "step4_raw_regions/step4_raw_region_color_image.png"),
    ],
    5: [
        (
            "step5_border_cleaned_preview",
            "step5_border_cleanup/step5_border_cleaned_preview.png",
        ),
    ],
    6: [
        (
            "step6_final_region_color_image",
            "step6_island_cleanup/step6_final_region_color_image.png",
        ),
    ],
    7: [
        ("step7_pbn_template", "step7_template/step7_pbn_template.png"),
        ("step7_palette_sheet", "step7_template/step7_palette_sheet.png"),
    ],
    8: [
        ("pbn_final", "step8_pdf/pbn_final.png"),
        ("pbn_final_palette", "step8_pdf/pbn_final_palette.png"),
    ],
}
