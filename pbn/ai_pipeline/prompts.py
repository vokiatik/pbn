from __future__ import annotations

from .models import SimplificationInstructions


CATEGORY_ADDITIONS = {
    "portrait": "Prioritize broad face, hair, clothing, and background color shapes.",
    "pet": "Prioritize broad body, ear, coat-patch, and background color shapes.",
    "landscape": "Prioritize major landforms, sky bands, water edges, tree masses, paths, and horizon structure.",
    "architecture": "Prioritize straight edges, windows, doors, rooflines, perspective, and major facade details.",
    "still_life": "Prioritize object silhouettes, overlaps, labels as shapes without readable text, shadows, and highlights.",
    "illustration": "Preserve the established style while converting the image into clean paintable colour regions.",
}


def build_simplification_prompt(instructions: SimplificationInstructions) -> str:
    preserve = ", ".join(instructions.preserve_elements) or "none specified"
    simplify = ", ".join(instructions.simplify_elements) or "photographic noise, texture, clutter and gradients"
    category_addition = CATEGORY_ADDITIONS.get(instructions.category.lower(), CATEGORY_ADDITIONS["illustration"])
    guidance = instructions.prompt_guidance.strip()
    guidance_section = f"\n\nAdditional user guidance:\n{guidance}" if guidance else ""

    return f"""Edit the provided image into a simple paint-by-number style illustration.

Keep the original pose, composition, and crop. Use exactly {instructions.target_palette_size} flat, reusable colors across the whole image. Use broad, closed, hard-edged color regions; no gradients, antialiasing, transparency, text, numbers, outlines, or photorealistic shading.

Simplify texture, clutter, repeated patterns, small highlights, and thin details into larger paintable shapes. Preserve these important elements when practical: {preserve}. Simplify these elements especially: {simplify}.

Prefer fewer, larger regions with smooth borders. Do not add objects or change the pose or crop. {category_addition}
{guidance_section}

Output only one flat-color illustration, not a numbered template. Canvas: {instructions.output_width}x{instructions.output_height}.""".strip()
