# PBN Studio Frontend Look Prompt

Use this as a prompt to recreate a similar frontend in another project.

Build a React + TypeScript single-page app with Vite and Material UI. The visual style should feel like a calm production dashboard for an image-processing studio, not a landing page. Use a warm off-white paper background, dark navy text, soft peach and pale blue page accents, and one orange accent color for primary actions. Use the Space Grotesk font or a similar geometric sans-serif.

The app shell has a sticky transparent top app bar with subtle backdrop blur. The left side shows the product name, `PBN Studio`, in bold text. The right side has simple text buttons for `Upload` and `Projects`. Page content sits in a wide centered container with generous vertical padding.

## Main Screens

- Upload screen: large title, short helper text, and a large dashed drag-and-drop upload panel. The upload panel has centered text, a contained `Choose File` button, soft hover/drag styling, and an inline loading spinner/message while uploading.
- Projects screen: operational table view inside a paper surface. Show project id, user, status chip, pipeline version, phase, dates, file count, original filename, and actions. Use compact open/delete buttons, pagination at the bottom right, and responsive wrapping so table text does not overflow.
- Project detail screen: title row with project id and delete button, status chip, and a two-column workspace. The left column is an AI generation settings panel with provider toggle, category field, palette-size slider, fit-mode select, preserve/simplify text fields, AI guidance, and status-aware generate/regenerate/proceed actions. The right column is an outputs panel that renders generated image previews or download buttons for non-image artifacts. A generated-files table appears below the workspace.

## Component Style

- Use Material UI `Paper` for functional panels only, with moderate padding and small border radii.
- Use `Stack`, `Box`, `Container`, `Typography`, `Button`, `Table`, `CircularProgress`, `Chip`, `Select`, `Slider`, and `ToggleButtonGroup`.
- Keep the UI dense enough for real work, but airy and readable.
- Use status chips for project state.
- Use image previews with a thin pale border, small rounded corners, and `width: 100%`.
- Use responsive layout: columns collapse into a single column on mobile.
- Avoid decorative hero sections, marketing cards, oversized typography, and purely ornamental illustrations. The first screen should be the usable app.

## Suggested Palette

- Background paper: `#fffdf9`
- Soft page base: `#f5efe6`
- Text: `#15203a`
- Primary accent: `#f05d23`
- Muted border: `#d7dfef`
- Drag/drop inactive border: `#9aa8c7`
- Drag/drop active fill: `#fff4ee`

## Interaction Behavior

- Upload validates PNG, JPEG, WEBP, HEIC, and HEIF, then navigates directly to the project detail page.
- Project detail pages update status and files from WebSocket events and project reloads.
- Generation controls disable while a run is queued or processing.
- Empty output states should use quiet secondary text, not large illustrations.
