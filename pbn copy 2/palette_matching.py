from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from skimage import color
from sklearn.cluster import MiniBatchKMeans

from .pbn_config import PaletteBudgetConfig, PaletteColor


@dataclass
class PaletteDataV2:
    numbers: np.ndarray
    names: list[str]
    hex_codes: list[str]
    rgb: np.ndarray
    lab: np.ndarray


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    text = hex_color.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"Invalid hex color: {hex_color}")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def build_palette_data(palette: list[PaletteColor]) -> PaletteDataV2:
    numbers = np.array([p.number for p in palette], dtype=np.int32)
    names = [p.name for p in palette]
    hex_codes = [p.hex.upper() for p in palette]
    rgb = np.array([hex_to_rgb(h) for h in hex_codes], dtype=np.uint8)
    rgb01 = rgb.astype(np.float32)[None, :, :] / 255.0
    lab = color.rgb2lab(rgb01).reshape(-1, 3).astype(np.float32)
    return PaletteDataV2(numbers=numbers, names=names, hex_codes=hex_codes, rgb=rgb, lab=lab)


def _lab_rows_to_rgb(lab_rows: np.ndarray) -> np.ndarray:
    rgb01 = color.lab2rgb(lab_rows[None, :, :]).reshape(-1, 3)
    rgb = np.clip(np.round(rgb01 * 255.0), 0, 255).astype(np.uint8)
    return rgb


def _kmeans_lab(points: np.ndarray, weights: np.ndarray, k: int) -> np.ndarray:
    n = int(points.shape[0])
    if n == 0:
        return np.zeros((0, 3), dtype=np.float32)
    k = int(max(1, min(k, n)))
    if n <= k:
        return points.astype(np.float32)
    km = MiniBatchKMeans(
        n_clusters=k,
        random_state=42,
        n_init=4,
        max_iter=220,
        batch_size=min(4096, max(256, n)),
    )
    km.fit(points, sample_weight=np.maximum(weights, 1e-3))
    return km.cluster_centers_.astype(np.float32)


def classify_superpixels_by_semantics(
    sp_labels: np.ndarray,
    n_superpixels: int,
    masks: dict[str, np.ndarray],
) -> np.ndarray:
    category_order = ["skin", "hair", "subject", "background", "accents"]
    score_stack = np.zeros((len(category_order), n_superpixels), dtype=np.float32)
    flat_sp = sp_labels.ravel().astype(np.int32)
    counts = np.bincount(flat_sp, minlength=n_superpixels).astype(np.float32)
    counts = np.maximum(counts, 1.0)

    for i, name in enumerate(category_order):
        m = masks[name].astype(np.float32).ravel()
        score_stack[i] = np.bincount(flat_sp, weights=m, minlength=n_superpixels).astype(np.float32) / counts

    # Bias toward foreground accents so tiny high-saliency details are less likely to flatten.
    score_stack[4] = np.maximum(score_stack[4], 0.55 * masks["p1_sp"])  # accents
    return np.argmax(score_stack, axis=0).astype(np.int32)


def _merge_candidates(
    labs: np.ndarray,
    cats: np.ndarray,
    weights: np.ndarray,
    target_size: int,
    skin_protect_delta: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if labs.shape[0] <= target_size:
        return labs, cats, weights

    alive = np.ones((labs.shape[0],), dtype=bool)
    labs = labs.astype(np.float32)
    cats = cats.astype(np.int32)
    weights = np.maximum(weights.astype(np.float32), 1e-4)

    def active_idx() -> np.ndarray:
        return np.flatnonzero(alive)

    while np.count_nonzero(alive) > target_size:
        idx = active_idx()
        x = labs[idx]
        c = cats[idx]
        w = weights[idx]
        d = color.deltaE_ciede2000(x[:, None, :], x[None, :, :]).astype(np.float32)
        np.fill_diagonal(d, np.inf)

        # Skin protection: prevent early skin/non-skin merges unless very close.
        skin = c == 0
        cross = np.logical_xor(skin[:, None], skin[None, :])
        d[cross] += 4.5

        # Softly protect accents and subject tones.
        subject_or_accent = (c == 2) | (c == 4)
        d[np.logical_and(subject_or_accent[:, None], subject_or_accent[None, :])] += 0.8

        ai, aj = np.unravel_index(np.argmin(d), d.shape)
        if not np.isfinite(d[ai, aj]):
            break

        if skin[ai] != skin[aj] and d[ai, aj] > skin_protect_delta:
            d[ai, aj] = np.inf
            ai2, aj2 = np.unravel_index(np.argmin(d), d.shape)
            if not np.isfinite(d[ai2, aj2]):
                break
            ai, aj = ai2, aj2

        i_abs = int(idx[ai])
        j_abs = int(idx[aj])
        wi = float(weights[i_abs])
        wj = float(weights[j_abs])
        tw = wi + wj
        labs[i_abs] = (labs[i_abs] * wi + labs[j_abs] * wj) / max(tw, 1e-6)
        weights[i_abs] = tw
        if wi < wj:
            cats[i_abs] = cats[j_abs]
        alive[j_abs] = False

    idx = np.flatnonzero(alive)
    return labs[idx], cats[idx], weights[idx]


def build_semantic_budgeted_palette(
    mean_lab: np.ndarray,
    area: np.ndarray,
    sp_categories: np.ndarray,
    budget: PaletteBudgetConfig,
    target_size: int,
) -> tuple[PaletteDataV2, np.ndarray]:
    budgets = {
        0: int(budget.skin_face_hands),
        1: int(budget.hair),
        2: int(budget.clothing_subject),
        3: int(budget.background),
        4: int(budget.accents),
    }

    cand_lab: list[np.ndarray] = []
    cand_cat: list[np.ndarray] = []
    cand_w: list[np.ndarray] = []
    for cat_idx in range(5):
        mask = sp_categories == cat_idx
        if not np.any(mask):
            continue
        pts = mean_lab[mask]
        # Boost small-detail priorities to preserve local variation.
        base_w = np.sqrt(np.maximum(area[mask].astype(np.float32), 1.0))
        if cat_idx == 0:
            base_w *= 1.35
        elif cat_idx == 4:
            base_w *= 1.25
        elif cat_idx == 3:
            base_w *= 0.9
        k = max(1, min(int(budgets[cat_idx]), int(pts.shape[0])))
        centers = _kmeans_lab(pts, base_w, k)
        cand_lab.append(centers)
        cand_cat.append(np.full((centers.shape[0],), cat_idx, dtype=np.int32))
        cand_w.append(np.full((centers.shape[0],), float(np.mean(base_w)), dtype=np.float32))

    if not cand_lab:
        # Fallback for edge cases.
        centers = _kmeans_lab(mean_lab, np.sqrt(np.maximum(area.astype(np.float32), 1.0)), target_size)
        cats = np.full((centers.shape[0],), 2, dtype=np.int32)
        weights = np.ones((centers.shape[0],), dtype=np.float32)
    else:
        centers = np.concatenate(cand_lab, axis=0).astype(np.float32)
        cats = np.concatenate(cand_cat, axis=0).astype(np.int32)
        weights = np.concatenate(cand_w, axis=0).astype(np.float32)

    merged_lab, merged_cat, _ = _merge_candidates(
        labs=centers,
        cats=cats,
        weights=weights,
        target_size=int(target_size),
        skin_protect_delta=10.5,
    )

    rgb = _lab_rows_to_rgb(merged_lab)
    order = np.argsort(merged_lab[:, 0], kind="stable")
    merged_lab = merged_lab[order]
    merged_cat = merged_cat[order]
    rgb = rgb[order]

    numbers = np.arange(1, merged_lab.shape[0] + 1, dtype=np.int32)
    cat_names = {
        0: "Skin",
        1: "Hair",
        2: "Subject",
        3: "Background",
        4: "Accent",
    }
    names = [f"{cat_names.get(int(c), 'Color')} {int(i):02d}" for i, c in zip(numbers.tolist(), merged_cat.tolist())]
    hex_codes = [f"#{int(r):02X}{int(g):02X}{int(b):02X}" for r, g, b in rgb.tolist()]
    palette = PaletteDataV2(numbers=numbers, names=names, hex_codes=hex_codes, rgb=rgb, lab=merged_lab.astype(np.float32))
    return palette, merged_cat.astype(np.int32)


def assign_superpixels_to_palette(mean_lab: np.ndarray, area: np.ndarray, palette_lab: np.ndarray) -> np.ndarray:
    d = color.deltaE_ciede2000(mean_lab[:, None, :], palette_lab[None, :, :]).astype(np.float32)
    return np.argmin(d, axis=1).astype(np.int32)


def assign_superpixels_to_palette_semantic(
    mean_lab: np.ndarray,
    area: np.ndarray,
    palette_lab: np.ndarray,
    sp_categories: np.ndarray,
    palette_categories: np.ndarray,
) -> np.ndarray:
    d = color.deltaE_ciede2000(mean_lab[:, None, :], palette_lab[None, :, :]).astype(np.float32)

    # Category-aware penalties: keep skin/fine details from collapsing into background bins.
    same = sp_categories[:, None] == palette_categories[None, :]
    d = d + np.where(same, 0.0, 1.25)

    skin_sp = sp_categories == 0
    skin_pal = palette_categories == 0
    bad_skin = np.logical_and(skin_sp[:, None], np.logical_not(skin_pal[None, :]))
    d[bad_skin] += 3.4

    # Tiny-detail accents should not be overly pushed to large flat bins.
    med_area = float(np.median(area)) if area.size else 1.0
    tiny = np.clip((med_area - area.astype(np.float32)) / max(med_area, 1.0), 0.0, 1.0)
    bg_pal = palette_categories == 3
    d[:, bg_pal] += tiny[:, None] * 0.9

    return np.argmin(d, axis=1).astype(np.int32)


def quantize_image_lab(
    image_rgb: np.ndarray,
    n_colors: int,
    weight_map: np.ndarray | None = None,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    h, w = image_rgb.shape[:2]
    rgb01 = image_rgb.astype(np.float32) / 255.0
    lab = color.rgb2lab(rgb01).astype(np.float32)
    flat = lab.reshape(-1, 3)

    if weight_map is None:
        weights = np.ones((flat.shape[0],), dtype=np.float32)
    else:
        wm = weight_map.astype(np.float32)
        if wm.shape != (h, w):
            wm = cv2.resize(wm, (w, h), interpolation=cv2.INTER_LINEAR)
        weights = np.clip(wm.reshape(-1), 0.0, None) + 1e-3

    n = flat.shape[0]
    k = int(max(2, min(int(n_colors), n)))
    km = MiniBatchKMeans(
        n_clusters=k,
        random_state=int(random_state),
        n_init=4,
        max_iter=220,
        batch_size=min(8192, max(512, n)),
    )
    km.fit(flat, sample_weight=weights)
    labels = km.predict(flat).astype(np.int32).reshape(h, w)
    centers_lab = km.cluster_centers_.astype(np.float32)
    centers_rgb = _lab_rows_to_rgb(centers_lab)
    quant_rgb = centers_rgb[labels].astype(np.uint8)
    return labels, centers_lab, centers_rgb, quant_rgb


def classify_pixels_by_semantics(masks: dict[str, np.ndarray]) -> np.ndarray:
    # 0 skin/face/hands, 1 hair, 2 subject/clothing, 3 background, 4 accents
    shape = masks["background"].shape
    out = np.full(shape, 3, dtype=np.int32)

    bg = masks["background"] > 0
    subject = masks["subject"] > 0
    hair = masks["hair"] > 0
    skin = masks["skin"] > 0
    accents = masks["accents"] > 0

    out[bg] = 3
    out[subject] = 2
    out[hair] = 1
    out[skin] = 0
    out[accents] = 4
    return out


def build_semantic_budgeted_palette_from_pixels(
    image_rgb: np.ndarray,
    pixel_categories: np.ndarray,
    budget: PaletteBudgetConfig,
    target_size: int,
) -> tuple[PaletteDataV2, np.ndarray]:
    h, w = image_rgb.shape[:2]
    lab = color.rgb2lab(image_rgb.astype(np.float32) / 255.0).astype(np.float32)
    flat_lab = lab.reshape(-1, 3)
    flat_cat = pixel_categories.reshape(-1).astype(np.int32)

    budgets = {
        0: int(budget.skin_face_hands),
        1: int(budget.hair),
        2: int(budget.clothing_subject),
        3: int(budget.background),
        4: int(budget.accents),
    }

    cand_lab: list[np.ndarray] = []
    cand_cat: list[np.ndarray] = []
    cand_w: list[np.ndarray] = []

    for cat_idx in range(5):
        ids = np.flatnonzero(flat_cat == cat_idx)
        if ids.size == 0:
            continue
        pts = flat_lab[ids]
        if ids.size > 120000:
            pick = np.random.default_rng(42).choice(ids, size=120000, replace=False)
            pts = flat_lab[pick]
        weights = np.ones((pts.shape[0],), dtype=np.float32)
        if cat_idx == 0:
            weights *= 1.4
        elif cat_idx == 4:
            weights *= 1.25
        elif cat_idx == 3:
            weights *= 0.9
        k = max(1, min(int(budgets[cat_idx]), int(pts.shape[0])))
        centers = _kmeans_lab(pts, weights, k)
        cand_lab.append(centers)
        cand_cat.append(np.full((centers.shape[0],), cat_idx, dtype=np.int32))
        cand_w.append(np.full((centers.shape[0],), float(np.mean(weights)), dtype=np.float32))

    if not cand_lab:
        centers = _kmeans_lab(flat_lab, np.ones((flat_lab.shape[0],), dtype=np.float32), int(target_size))
        cats = np.full((centers.shape[0],), 2, dtype=np.int32)
        weights = np.ones((centers.shape[0],), dtype=np.float32)
    else:
        centers = np.concatenate(cand_lab, axis=0).astype(np.float32)
        cats = np.concatenate(cand_cat, axis=0).astype(np.int32)
        weights = np.concatenate(cand_w, axis=0).astype(np.float32)

    merged_lab, merged_cat, _ = _merge_candidates(
        labs=centers,
        cats=cats,
        weights=weights,
        target_size=int(target_size),
        skin_protect_delta=10.5,
    )

    rgb = _lab_rows_to_rgb(merged_lab)
    order = np.argsort(merged_lab[:, 0], kind="stable")
    merged_lab = merged_lab[order]
    merged_cat = merged_cat[order]
    rgb = rgb[order]

    numbers = np.arange(1, merged_lab.shape[0] + 1, dtype=np.int32)
    cat_names = {
        0: "Skin",
        1: "Hair",
        2: "Subject",
        3: "Background",
        4: "Accent",
    }
    names = [f"{cat_names.get(int(c), 'Color')} {int(i):02d}" for i, c in zip(numbers.tolist(), merged_cat.tolist())]
    hex_codes = [f"#{int(r):02X}{int(g):02X}{int(b):02X}" for r, g, b in rgb.tolist()]
    palette = PaletteDataV2(numbers=numbers, names=names, hex_codes=hex_codes, rgb=rgb, lab=merged_lab.astype(np.float32))
    return palette, merged_cat.astype(np.int32)


def assign_pixels_to_palette_semantic(
    image_rgb: np.ndarray,
    palette_lab: np.ndarray,
    pixel_categories: np.ndarray,
    palette_categories: np.ndarray,
) -> np.ndarray:
    lab = color.rgb2lab(image_rgb.astype(np.float32) / 255.0).astype(np.float32)
    h, w = lab.shape[:2]
    flat = lab.reshape(-1, 3)
    d = color.deltaE_ciede2000(flat[:, None, :], palette_lab[None, :, :]).astype(np.float32)

    cats = pixel_categories.reshape(-1).astype(np.int32)
    same = cats[:, None] == palette_categories[None, :]
    d = d + np.where(same, 0.0, 1.2)

    skin_px = cats == 0
    skin_pal = palette_categories == 0
    bad_skin = np.logical_and(skin_px[:, None], np.logical_not(skin_pal[None, :]))
    d[bad_skin] += 3.3

    labels = np.argmin(d, axis=1).astype(np.int32)
    return labels.reshape(h, w)
