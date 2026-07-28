import {
    Alert,
    Box,
    Button,
    CircularProgress,
    FormControl,
    InputLabel,
    MenuItem,
    Select,
    Stack,
    ToggleButton,
    ToggleButtonGroup,
    Typography,
} from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";

import {
    deleteDetailProtection,
    getDetailProtection,
    getDetailProtectionMask,
    putDetailProtection,
} from "../../api/client";

type Props = {
    publicId: string;
    src: string;
    disabled?: boolean;
    onDirtyChange?: (dirty: boolean) => void;
    onSaved: () => Promise<void> | void;
};

type Tool = "lasso" | "paint" | "erase";
type Size = { width: number; height: number };
type Point = { x: number; y: number };
type ActiveDrawing = Point & { pointerId: number; lassoPoints?: Point[] };

const brushSizes = [1, 3, 6] as const;
const maximumHistory = 10;

export function DetailProtectionEditor({ publicId, src, disabled, onDirtyChange, onSaved }: Props) {
    const visibleCanvas = useRef<HTMLCanvasElement | null>(null);
    const maskCanvas = useRef<HTMLCanvasElement | null>(null);
    const drawing = useRef<ActiveDrawing | null>(null);
    const history = useRef<ImageData[]>([]);
    const historyIndex = useRef(-1);
    const [size, setSize] = useState<Size | null>(null);
    const [tool, setTool] = useState<Tool>("lasso");
    const [brushPercent, setBrushPercent] = useState<number>(3);
    const [coverage, setCoverage] = useState(0);
    const [dirty, setDirty] = useState(false);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [historyVersion, setHistoryVersion] = useState(0);

    const setDirtyState = useCallback((value: boolean) => {
        setDirty(value);
        onDirtyChange?.(value);
    }, [onDirtyChange]);

    const renderOverlay = useCallback(() => {
        const source = maskCanvas.current;
        const target = visibleCanvas.current;
        if (!source || !target) return;
        const sourceContext = source.getContext("2d", { willReadFrequently: true });
        const targetContext = target.getContext("2d");
        if (!sourceContext || !targetContext) return;
        const pixels = sourceContext.getImageData(0, 0, source.width, source.height);
        const overlay = targetContext.createImageData(source.width, source.height);
        for (let index = 0; index < pixels.data.length; index += 4) {
            if (pixels.data[index] < 128) continue;
            overlay.data[index] = 23;
            overlay.data[index + 1] = 72;
            overlay.data[index + 2] = 160;
            overlay.data[index + 3] = 105;
        }
        targetContext.putImageData(overlay, 0, 0);
    }, []);

    const updateCoverage = useCallback(() => {
        const canvas = maskCanvas.current;
        const context = canvas?.getContext("2d", { willReadFrequently: true });
        if (!canvas || !context) return;
        const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
        let selected = 0;
        for (let index = 0; index < data.length; index += 4) {
            if (data[index] >= 128) selected++;
        }
        setCoverage(100 * selected / Math.max(1, canvas.width * canvas.height));
    }, []);

    const pushHistory = useCallback(() => {
        const canvas = maskCanvas.current;
        const context = canvas?.getContext("2d", { willReadFrequently: true });
        if (!canvas || !context) return;
        const next = history.current.slice(0, historyIndex.current + 1);
        next.push(context.getImageData(0, 0, canvas.width, canvas.height));
        if (next.length > maximumHistory) next.shift();
        history.current = next;
        historyIndex.current = next.length - 1;
        setHistoryVersion((value) => value + 1);
    }, []);

    useEffect(() => {
        let cancelled = false;
        let objectUrl: string | null = null;
        setLoading(true);
        setError(null);
        getDetailProtection(publicId)
            .then(async (metadata) => {
                if (!metadata.exists) return null;
                const blob = await getDetailProtectionMask(publicId);
                objectUrl = URL.createObjectURL(blob);
                return objectUrl;
            })
            .then((maskUrl) => {
                if (cancelled || !size) return;
                initializeMask(size, maskUrl, maskCanvas, () => {
                    if (cancelled) return;
                    renderOverlay();
                    updateCoverage();
                    history.current = [];
                    historyIndex.current = -1;
                    pushHistory();
                    setDirtyState(false);
                    setLoading(false);
                });
            })
            .catch((reason) => {
                if (!cancelled) {
                    setError(reason instanceof Error ? reason.message : "Failed to load detail protection");
                    setLoading(false);
                }
            });
        return () => {
            cancelled = true;
            if (objectUrl) URL.revokeObjectURL(objectUrl);
        };
    }, [publicId, pushHistory, renderOverlay, setDirtyState, size, updateCoverage]);

    const drawTo = (event: PointerEvent<HTMLCanvasElement>, startNew: boolean) => {
        const canvas = visibleCanvas.current;
        const mask = maskCanvas.current;
        const context = mask?.getContext("2d");
        const overlayContext = canvas?.getContext("2d");
        if (!canvas || !mask || !context || !overlayContext || disabled || saving) return;
        const bounds = canvas.getBoundingClientRect();
        const x = (event.clientX - bounds.left) * mask.width / bounds.width;
        const y = (event.clientY - bounds.top) * mask.height / bounds.height;
        const previous = drawing.current;
        if (!startNew && previous?.pointerId !== event.pointerId) return;
        if (tool === "lasso") {
            const nextPoint = { x, y };
            if (startNew || !previous) {
                renderOverlay();
                drawing.current = { pointerId: event.pointerId, ...nextPoint, lassoPoints: [nextPoint] };
                return;
            }
            const points = previous.lassoPoints ?? [];
            const last = points[points.length - 1];
            if (!last || Math.hypot(x - last.x, y - last.y) < 1) return;
            overlayContext.beginPath();
            overlayContext.moveTo(last.x, last.y);
            overlayContext.lineTo(x, y);
            overlayContext.strokeStyle = "rgba(23, 72, 160, 0.9)";
            overlayContext.lineWidth = Math.max(2, Math.min(mask.width, mask.height) * 0.003);
            overlayContext.lineCap = "round";
            overlayContext.stroke();
            drawing.current = {
                pointerId: event.pointerId,
                ...nextPoint,
                lassoPoints: [...points, nextPoint],
            };
            return;
        }
        const lineWidth = Math.max(1, Math.min(mask.width, mask.height) * brushPercent / 100);
        context.strokeStyle = tool === "paint" ? "#fff" : "#000";
        context.fillStyle = context.strokeStyle;
        context.lineCap = "round";
        context.lineJoin = "round";
        context.lineWidth = lineWidth;
        overlayContext.globalCompositeOperation = tool === "paint" ? "source-over" : "destination-out";
        overlayContext.strokeStyle = "rgba(23, 72, 160, 0.41)";
        overlayContext.fillStyle = overlayContext.strokeStyle;
        overlayContext.lineCap = "round";
        overlayContext.lineJoin = "round";
        overlayContext.lineWidth = lineWidth;
        if (startNew || !previous) {
            context.beginPath();
            context.arc(x, y, lineWidth / 2, 0, Math.PI * 2);
            context.fill();
            overlayContext.beginPath();
            overlayContext.arc(x, y, lineWidth / 2, 0, Math.PI * 2);
            overlayContext.fill();
        } else {
            context.beginPath();
            context.moveTo(previous.x, previous.y);
            context.lineTo(x, y);
            context.stroke();
            overlayContext.beginPath();
            overlayContext.moveTo(previous.x, previous.y);
            overlayContext.lineTo(x, y);
            overlayContext.stroke();
        }
        overlayContext.globalCompositeOperation = "source-over";
        drawing.current = { pointerId: event.pointerId, x, y };
    };

    const finishDrawing = (pointerId: number, commit = true) => {
        const active = drawing.current;
        if (active?.pointerId !== pointerId) return;
        drawing.current = null;
        if (active.lassoPoints) {
            const canvas = maskCanvas.current;
            const context = canvas?.getContext("2d");
            if (commit && canvas && context && active.lassoPoints.length >= 3) {
                const [first, ...rest] = active.lassoPoints;
                context.beginPath();
                context.moveTo(first.x, first.y);
                rest.forEach((point) => context.lineTo(point.x, point.y));
                context.closePath();
                context.fillStyle = "#fff";
                context.fill();
                pushHistory();
                updateCoverage();
                setDirtyState(true);
            }
            renderOverlay();
            return;
        }
        pushHistory();
        updateCoverage();
        setDirtyState(true);
    };

    const restoreHistory = (index: number) => {
        const canvas = maskCanvas.current;
        const context = canvas?.getContext("2d");
        const state = history.current[index];
        if (!canvas || !context || !state) return;
        context.putImageData(state, 0, 0);
        historyIndex.current = index;
        setHistoryVersion((value) => value + 1);
        renderOverlay();
        updateCoverage();
        setDirtyState(true);
    };

    const clearMask = () => {
        const canvas = maskCanvas.current;
        const context = canvas?.getContext("2d");
        if (!canvas || !context || disabled) return;
        context.fillStyle = "#000";
        context.fillRect(0, 0, canvas.width, canvas.height);
        renderOverlay();
        updateCoverage();
        pushHistory();
        setDirtyState(true);
    };

    const save = async () => {
        const canvas = maskCanvas.current;
        if (!canvas) return;
        setSaving(true);
        setError(null);
        try {
            if (coverage <= 0) {
                await deleteDetailProtection(publicId);
            } else {
                const blob = await canvasBlob(canvas);
                await putDetailProtection(publicId, blob);
            }
            setDirtyState(false);
            await onSaved();
        } catch (reason) {
            setError(reason instanceof Error ? reason.message : "Failed to save detail protection");
        } finally {
            setSaving(false);
        }
    };

    return (
        <Stack spacing={1.5}>
            <Stack spacing={0.5}>
                <Typography variant="h6">Preserve important details</Typography>
                <Typography variant="body2" color="text.secondary">
                    Drag a lasso around each area that needs finer local geometry, then release to fill it.
                    Paint and erase can refine the selection. Only the filled blue area is protected.
                </Typography>
            </Stack>

            {error && <Alert severity="error">{error}</Alert>}
            {coverage > 40 && (
                <Alert severity="warning">
                    {coverage.toFixed(1)}% is selected. Advanced processing is allowed but may take considerably longer.
                </Alert>
            )}

            <Box sx={{ position: "relative", width: "100%", bgcolor: "#f8fafc", borderRadius: 1, overflow: "hidden", border: "1px solid #d7dfef" }}>
                <Box
                    component="img"
                    src={src}
                    alt="Reviewed AI image for detail protection"
                    draggable={false}
                    onLoad={(event) => {
                        const next = { width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight };
                        setSize(next);
                        const canvas = visibleCanvas.current;
                        if (canvas) {
                            canvas.width = next.width;
                            canvas.height = next.height;
                        }
                    }}
                    sx={{ display: "block", width: "100%", height: "auto", userSelect: "none" }}
                />
                <Box
                    component="canvas"
                    ref={visibleCanvas}
                    onPointerDown={(event) => {
                        if (disabled || saving) return;
                        event.currentTarget.setPointerCapture(event.pointerId);
                        drawTo(event, true);
                    }}
                    onPointerMove={(event) => {
                        if (drawing.current?.pointerId === event.pointerId) drawTo(event, false);
                    }}
                    onPointerUp={(event) => {
                        drawTo(event, false);
                        finishDrawing(event.pointerId);
                    }}
                    onPointerCancel={(event) => { finishDrawing(event.pointerId, tool !== "lasso"); }}
                    sx={{ position: "absolute", inset: 0, width: "100%", height: "100%", cursor: disabled ? "default" : "crosshair", touchAction: "none" }}
                />
                {(loading || !size) && (
                    <Box sx={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", bgcolor: "rgba(255,255,255,0.7)" }}>
                        <CircularProgress size={28} />
                    </Box>
                )}
            </Box>

            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ sm: "center" }}>
                <ToggleButtonGroup
                    exclusive
                    size="small"
                    value={tool}
                    disabled={disabled || saving}
                    onChange={(_, value: Tool | null) => { if (value) setTool(value); }}
                >
                    <ToggleButton value="lasso">Lasso area</ToggleButton>
                    <ToggleButton value="paint">Paint</ToggleButton>
                    <ToggleButton value="erase">Erase</ToggleButton>
                </ToggleButtonGroup>
                <FormControl size="small" sx={{ minWidth: 140 }}>
                    <InputLabel>Brush size</InputLabel>
                    <Select
                        label="Brush size"
                        value={brushPercent}
                        disabled={disabled || saving || tool === "lasso"}
                        onChange={(event) => setBrushPercent(Number(event.target.value))}
                    >
                        {brushSizes.map((value) => <MenuItem key={value} value={value}>{value}%</MenuItem>)}
                    </Select>
                </FormControl>
                <Button disabled={disabled || saving || historyIndex.current <= 0} onClick={() => restoreHistory(historyIndex.current - 1)}>Undo</Button>
                <Button disabled={disabled || saving || historyIndex.current >= history.current.length - 1} onClick={() => restoreHistory(historyIndex.current + 1)}>Redo</Button>
                <Button disabled={disabled || saving || coverage <= 0} onClick={clearMask}>Clear</Button>
                <Box sx={{ flex: 1 }} />
                <Typography variant="body2" color="text.secondary">{coverage.toFixed(1)}% selected</Typography>
            </Stack>

            <Button variant="outlined" disabled={disabled || saving || loading || !dirty} onClick={() => void save()}>
                {saving ? <CircularProgress size={20} /> : "Save detail protection"}
            </Button>
            {dirty && <Alert severity="info">Save the protection mask before generating PBN options.</Alert>}
            <Box sx={{ display: "none" }}>{historyVersion}</Box>
        </Stack>
    );
}

function initializeMask(
    size: Size,
    maskUrl: string | null,
    maskRef: { current: HTMLCanvasElement | null },
    complete: () => void,
) {
    const canvas = document.createElement("canvas");
    canvas.width = size.width;
    canvas.height = size.height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return;
    context.fillStyle = "#000";
    context.fillRect(0, 0, size.width, size.height);
    maskRef.current = canvas;
    if (!maskUrl) {
        complete();
        return;
    }
    const image = new Image();
    image.onload = () => {
        context.drawImage(image, 0, 0, size.width, size.height);
        complete();
    };
    image.onerror = complete;
    image.src = maskUrl;
}

function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
    const normalized = document.createElement("canvas");
    normalized.width = canvas.width;
    normalized.height = canvas.height;
    const context = normalized.getContext("2d");
    const sourceContext = canvas.getContext("2d", { willReadFrequently: true });
    if (!context || !sourceContext) return Promise.reject(new Error("Failed to normalize protection mask"));
    const pixels = sourceContext.getImageData(0, 0, canvas.width, canvas.height);
    for (let index = 0; index < pixels.data.length; index += 4) {
        const value = pixels.data[index] >= 128 ? 255 : 0;
        pixels.data[index] = value;
        pixels.data[index + 1] = value;
        pixels.data[index + 2] = value;
        pixels.data[index + 3] = 255;
    }
    context.putImageData(pixels, 0, 0);
    return new Promise((resolve, reject) => {
        normalized.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Failed to encode protection mask")), "image/png");
    });
}
