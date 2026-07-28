from __future__ import annotations

from .models import SimplificationInstructions


CATEGORY_ADDITIONS = {
    "portrait": "Prioritize recognizable facial features, eyes, lips, hair masses, skin-tone planes, and expression.",
    "pet": "Prioritize eyes, nose, mouth, ears, breed markings, coat patches, and the animal's silhouette.",
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

    return f"""Transform the source image into a simplified paint-by-number source illustration.

Preserve the original crop, composition, main subject identity, pose, and the most important recognizable features.

STRICT PALETTE CONTRACT — THIS IS THE HIGHEST-PRIORITY OUTPUT REQUIREMENT:
- Use exactly {instructions.target_palette_size} distinct visible colors in the entire finished image: no more and no fewer.
- This is a hard numeric palette limit, not an approximate visual target and not a target for later processing.
- Choose the {instructions.target_palette_size}-color palette first, then construct every subject and background region exclusively from those same reusable colors.
- Reuse the exact same flat RGB color everywhere that paint is meant to match. Do not create almost-identical lighter, darker, warmer, cooler, or less-saturated variants.
- If the source contains more tones, replace every extra tone with the closest appropriate palette color. Merge perceptually similar source colors while preserving their color family, light-to-dark ordering, and the subject's recognizable identity.
- Allocate palette contrast to the main subject before the background. Eyes, pupils, nose, mouth, face boundaries, paws, and major markings must remain separate closed shapes whenever they define identity, using perceptually distinct neighboring colors selected from the same fixed palette.
- Simplify backgrounds and repeated patterns first. Background shading must reuse existing palette colors instead of consuming near-duplicate colors.
- Use hard pixel boundaries between palette colors. Do not introduce edge antialiasing, transparency, translucent overlays, soft shadows, glows, blended pixels, or gradient transition colors.
- Do not draw a palette strip, swatches, legend, text, or any demonstration of the selected colors.
- Before returning the image, internally verify that every visible pixel belongs to the fixed {instructions.target_palette_size}-color palette and remap any accidental extra shade to its nearest palette color.

Create a clean posterized image made from large, closed, hard-edged flat color regions. Use only broad color shapes that can become paintable regions.

Make region borders rounded and smoothly simplified wherever possible. Avoid jagged, stair-stepped, spiky, overly angular, or noisy borders unless a crisp geometric edge is essential to the subject.

Use the exact {instructions.target_palette_size}-color palette described above. Prefer fewer, larger regions over many small details, but do not introduce extra shades.

Keep subject-defining details recognizable: face shape, eyes, mouth, pose, silhouette, important markings, clothing or object boundaries, and major color blocks.

Simplify insignificant details aggressively. Do not preserve photographic realism when it creates many paint regions. Replace texture with a small number of broad representative color areas.

Simplify or merge:
- photographic texture
- skin pores, hair strands, fur strands, fabric weave
- shadows with soft gradients
- reflections
- background clutter
- tiny highlights
- small isolated color spots
- thin slivers
- pinholes and sharp micro-islands
- jagged border noise
- grass blades, leaf texture, sparkle dots, mottling, and repeated micro-patterns

Preserve only the important structure of:
{preserve}

Simplify especially:
{simplify}

Rules:
- no text
- no numbers
- no outlines
- no brush texture
- no dithering
- no noise
- no gradients
- no antialiasing or blended edge pixels
- no semi-realistic shading
- no tiny isolated islands
- no thin shapes
- no sharp slivers, pinholes, or jagged micro-islands
- no overly angular noisy borders
- no new objects
- no changed anatomy, pose, crop, or identity

If a detail would create many tiny regions, merge it into the nearest larger color region. Important eyes, mouth, facial features, markings, or object-defining details should remain recognizable but simplified into larger rounded paintable shapes.

Each region should be large enough to paint by hand. Tiny preserved details must be understandable, closed, rounded, and paintable. If a detail cannot be made paintable, simplify or merge it instead of leaving an unpaintable speck.

Prefer clean, smooth, paintable areas over fine detail.

Category guidance: {category_addition}
{guidance_section}

Output only the simplified flat-color illustration, not a numbered template.
Canvas: {instructions.output_width}x{instructions.output_height}.
Generate exactly one image.""".strip()
