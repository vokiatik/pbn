from __future__ import annotations

AI_PROGRESS = {
    "preparing_source": 10,
    "generating_ai_image": 25,
    "extracting_regions": 45,
    "normalizing_region_palette": 60,
    "cleaning_regions": 70,
    "validating_template": 80,
    "generating_template": 90,
    "exporting_pdf": 96,
    "completed": 100,
}

PUBLIC_AI_FILES = [
    ("ai_simplified", "pipeline_ai/ai/simplified.png"),
    ("ai_region_map", "pipeline_ai/regions/initial_region_map.png"),
    ("ai_palette_preview", "pipeline_ai/palette/preview.png"),
    ("ai_validation_report", "pipeline_ai/validation/report.json"),
    ("ai_numbered_template", "pipeline_ai/template/numbered_template.png"),
    ("ai_palette_sheet", "pipeline_ai/template/palette_sheet.png"),
    ("ai_painted_reference", "pipeline_ai/export/painted_reference.png"),
    ("ai_final", "pipeline_ai/export/pbn_final.png"),
    ("ai_final_palette", "pipeline_ai/export/pbn_final_palette.png"),
    ("ai_template_pdf", "pipeline_ai/export/pbn_template.pdf"),
    ("ai_palette_pdf", "pipeline_ai/export/palette_sheet.pdf"),
    ("ai_easy_painted_preview", "pipeline_ai/options/easy/painted_reference.png"),
    ("ai_easy_template_preview", "pipeline_ai/options/easy/numbered_template.png"),
    ("ai_medium_painted_preview", "pipeline_ai/options/medium/painted_reference.png"),
    ("ai_medium_template_preview", "pipeline_ai/options/medium/numbered_template.png"),
    ("ai_hard_painted_preview", "pipeline_ai/options/hard/painted_reference.png"),
    ("ai_hard_template_preview", "pipeline_ai/options/hard/numbered_template.png"),
]

PUBLIC_PBN_OPTION_FILES = [
    ("ai_simplified", "pipeline_ai/ai/simplified.png"),
    ("ai_easy_painted_preview", "pipeline_ai/options/easy/painted_reference.png"),
    ("ai_easy_template_preview", "pipeline_ai/options/easy/numbered_template.png"),
    ("ai_medium_painted_preview", "pipeline_ai/options/medium/painted_reference.png"),
    ("ai_medium_template_preview", "pipeline_ai/options/medium/numbered_template.png"),
    ("ai_hard_painted_preview", "pipeline_ai/options/hard/painted_reference.png"),
    ("ai_hard_template_preview", "pipeline_ai/options/hard/numbered_template.png"),
]

PUBLIC_AI_IMAGE_FILES = [
    ("ai_simplified", "pipeline_ai/ai/simplified.png"),
]
