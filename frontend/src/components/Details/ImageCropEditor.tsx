import { Box, Slider, Stack, Typography } from "@mui/material";
import { useEffect, useMemo, useRef, useState } from "react";
import type { PointerEvent } from "react";

import type { CropRect } from "../../api/client";

type Props = {
    src: string;
    orientation: "portrait" | "landscape";
    value: CropRect | null;
    disabled?: boolean;
    onChange: (crop: CropRect) => void;
    onSourceOrientation?: (orientation: "portrait" | "landscape") => void;
};

type Size = { width: number; height: number };

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

export function ImageCropEditor({ src, orientation, value, disabled, onChange, onSourceOrientation }: Props) {
    const [size, setSize] = useState<Size | null>(null);
    const drag = useRef<{ x: number; y: number; crop: CropRect } | null>(null);
    const targetRatio = orientation === "portrait" ? 1 / Math.SQRT2 : Math.SQRT2;

    const baseCrop = useMemo(() => size ? centeredCrop(size, targetRatio) : null, [size, targetRatio]);
    const crop = size && baseCrop ? normalizeCrop(value, baseCrop, size, targetRatio) : null;
    const zoom = crop && baseCrop ? clamp(baseCrop.width / crop.width, 1, 3) : 1;

    useEffect(() => {
        if (!disabled && baseCrop && (!value || !cropMatches(value, size!, targetRatio))) {
            onChange(baseCrop);
        }
    }, [baseCrop, disabled, onChange, size, targetRatio, value]);

    const updateZoom = (nextZoom: number) => {
        if (disabled || !baseCrop || !crop) return;
        const width = baseCrop.width / nextZoom;
        const height = baseCrop.height / nextZoom;
        const centerX = crop.x + crop.width / 2;
        const centerY = crop.y + crop.height / 2;
        onChange(constrainCrop({ x: centerX - width / 2, y: centerY - height / 2, width, height }));
    };

    const move = (event: PointerEvent<HTMLDivElement>) => {
        if (!drag.current || !crop || disabled) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        const dx = (event.clientX - drag.current.x) / bounds.width;
        const dy = (event.clientY - drag.current.y) / bounds.height;
        onChange(constrainCrop({
            ...drag.current.crop,
            x: drag.current.crop.x - dx * drag.current.crop.width,
            y: drag.current.crop.y - dy * drag.current.crop.height,
        }));
    };

    return (
        <Stack spacing={1}>
            <Typography variant="subtitle2">Print crop</Typography>
            <Box
                onPointerDown={(event) => {
                    if (!crop || disabled) return;
                    event.currentTarget.setPointerCapture(event.pointerId);
                    drag.current = { x: event.clientX, y: event.clientY, crop };
                }}
                onPointerMove={move}
                onPointerUp={() => { drag.current = null; }}
                onPointerCancel={() => { drag.current = null; }}
                sx={{
                    position: "relative",
                    overflow: "hidden",
                    width: "100%",
                    aspectRatio: `${targetRatio}`,
                    border: "1px solid #9aa8c7",
                    borderRadius: 1,
                    bgcolor: "#eef2f8",
                    cursor: disabled ? "default" : "grab",
                    touchAction: "none",
                }}
            >
                <Box
                    component="img"
                    src={src}
                    alt="Adjustable print crop"
                    draggable={false}
                    onLoad={(event) => {
                        const image = event.currentTarget;
                        const next = { width: image.naturalWidth, height: image.naturalHeight };
                        setSize(next);
                        onSourceOrientation?.(next.width >= next.height ? "landscape" : "portrait");
                    }}
                    sx={crop ? {
                        position: "absolute",
                        maxWidth: "none",
                        width: `${100 / crop.width}%`,
                        height: `${100 / crop.height}%`,
                        left: `${-100 * crop.x / crop.width}%`,
                        top: `${-100 * crop.y / crop.height}%`,
                        userSelect: "none",
                        pointerEvents: "none",
                    } : { width: "100%", height: "100%", objectFit: "contain" }}
                />
            </Box>
            <Typography variant="caption" color="text.secondary">
                Drag to position the crop. Zoom affects AI generation and the final print.
            </Typography>
            <Slider
                size="small"
                min={1}
                max={3}
                step={0.01}
                value={zoom}
                disabled={disabled || !crop}
                onChange={(_, next) => updateZoom(next as number)}
                aria-label="Crop zoom"
            />
        </Stack>
    );
}

function centeredCrop(size: Size, targetRatio: number): CropRect {
    const sourceRatio = size.width / size.height;
    const width = sourceRatio > targetRatio ? targetRatio / sourceRatio : 1;
    const height = sourceRatio > targetRatio ? 1 : sourceRatio / targetRatio;
    return { x: (1 - width) / 2, y: (1 - height) / 2, width, height };
}

function cropMatches(crop: CropRect, size: Size, targetRatio: number): boolean {
    const pixelRatio = crop.width * size.width / (crop.height * size.height);
    return Math.abs(pixelRatio - targetRatio) / targetRatio <= 0.01;
}

function normalizeCrop(value: CropRect | null, fallback: CropRect, size: Size, targetRatio: number): CropRect {
    if (!value || !cropMatches(value, size, targetRatio)) return fallback;
    return constrainCrop(value);
}

function constrainCrop(crop: CropRect): CropRect {
    const width = clamp(crop.width, 0.01, 1);
    const height = clamp(crop.height, 0.01, 1);
    return {
        x: clamp(crop.x, 0, 1 - width),
        y: clamp(crop.y, 0, 1 - height),
        width,
        height,
    };
}
