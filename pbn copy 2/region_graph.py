from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from .palette import PaletteData
from .superpixels import SuperpixelData


@dataclass
class RegionInfo:
    region_id: int
    color_label: int
    superpixels: list[int]
    area: int
    centroid_xy: tuple[float, float]
    bbox_xywh: tuple[int, int, int, int]


@dataclass
class BorderInfo:
    shared_border: int
    edge_mean: float
    lab_distance: float


@dataclass
class RegionGraph:
    sp_to_region: np.ndarray
    regions: dict[int, RegionInfo]
    borders: dict[tuple[int, int], BorderInfo]


def _region_bbox_and_centroid(sp_label_map: np.ndarray, region_superpixels: list[int]) -> tuple[tuple[int, int, int, int], tuple[float, float]]:
    mask = np.isin(sp_label_map, region_superpixels)
    ys, xs = np.where(mask)
    x0 = int(xs.min())
    y0 = int(ys.min())
    x1 = int(xs.max())
    y1 = int(ys.max())
    bbox = (x0, y0, x1 - x0 + 1, y1 - y0 + 1)
    centroid = (float(xs.mean()), float(ys.mean()))
    return bbox, centroid


def build_region_graph(sp_data: SuperpixelData, palette: PaletteData, sp_color_labels: np.ndarray) -> RegionGraph:
    n_sp = sp_data.count
    visited = np.zeros((n_sp,), dtype=bool)
    sp_to_region = np.full((n_sp,), -1, dtype=np.int32)

    regions: dict[int, RegionInfo] = {}
    next_region_id = 0

    for root in range(n_sp):
        if visited[root]:
            continue
        visited[root] = True
        color = int(sp_color_labels[root])
        q: deque[int] = deque([root])
        group: list[int] = []

        while q:
            s = q.popleft()
            group.append(s)
            for nb in sp_data.neighbors.get(s, {}):
                if visited[nb] or int(sp_color_labels[nb]) != color:
                    continue
                visited[nb] = True
                q.append(nb)

        for s in group:
            sp_to_region[s] = next_region_id

        area = int(sp_data.area[np.array(group, dtype=np.int32)].sum())
        bbox, centroid = _region_bbox_and_centroid(sp_data.labels, group)
        regions[next_region_id] = RegionInfo(
            region_id=next_region_id,
            color_label=color,
            superpixels=group,
            area=area,
            centroid_xy=centroid,
            bbox_xywh=bbox,
        )
        next_region_id += 1

    border_acc: dict[tuple[int, int], tuple[int, float]] = {}
    for s, nb_map in sp_data.neighbors.items():
        rs = int(sp_to_region[s])
        for nb, stat in nb_map.items():
            rn = int(sp_to_region[nb])
            if rs == rn:
                continue
            a = min(rs, rn)
            b = max(rs, rn)
            key = (a, b)
            prev_len, prev_edge_sum = border_acc.get(key, (0, 0.0))
            border_acc[key] = (
                prev_len + int(stat.length),
                prev_edge_sum + float(stat.edge_mean) * float(stat.length),
            )

    borders: dict[tuple[int, int], BorderInfo] = {}
    for (ra, rb), (shared, edge_sum) in border_acc.items():
        ca = regions[ra].color_label
        cb = regions[rb].color_label
        lab_dist = float(np.linalg.norm(palette.lab[ca] - palette.lab[cb]))
        borders[(ra, rb)] = BorderInfo(
            shared_border=int(shared),
            edge_mean=float(edge_sum / max(shared, 1)),
            lab_distance=lab_dist,
        )

    return RegionGraph(sp_to_region=sp_to_region, regions=regions, borders=borders)
