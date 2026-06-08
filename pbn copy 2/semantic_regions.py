from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .pbn_config import SemanticConfig


@dataclass
class SemanticMasks:
    face: np.ndarray
    hands: np.ndarray
    person: np.ndarray
    foreground: np.ndarray
    background: np.ndarray
    skin: np.ndarray
    hair: np.ndarray
    clothing: np.ndarray
    p1: np.ndarray
    p2: np.ndarray
    p3: np.ndarray
    debug_rgb: np.ndarray


def _normalize01(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.float32)
    x = x - float(x.min())
    vmax = float(x.max())
    if vmax <= 1e-6:
        return np.zeros_like(x, dtype=np.float32)
    return (x / vmax).astype(np.float32)


def _face_mask(gray: np.ndarray) -> np.ndarray:
    out = np.zeros_like(gray, dtype=np.uint8)
    try:
        cv2_data = getattr(cv2, "data", None)
        if cv2_data is None or not hasattr(cv2_data, "haarcascades"):
            return out
        cascade = cv2.CascadeClassifier(cv2_data.haarcascades + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            return out
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30))
        for x, y, w, h in faces:
            cv2.ellipse(out, (x + w // 2, y + h // 2), (max(4, w // 2), max(4, h // 2)), 0, 0, 360, 255, -1)
    except Exception:
        return out
    return out


def _saliency_map(bgr: np.ndarray) -> np.ndarray:
    saliency_ns = getattr(cv2, "saliency", None)
    if saliency_ns is None or not hasattr(saliency_ns, "StaticSaliencySpectralResidual_create"):
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
        return _normalize01(np.abs(lap))
    try:
        det = saliency_ns.StaticSaliencySpectralResidual_create()
        ok, sal = det.computeSaliency(bgr)
        if ok:
            return _normalize01(sal)
    except Exception:
        pass
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    return _normalize01(np.abs(lap))


def _skin_mask(rgb: np.ndarray) -> np.ndarray:
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    y = ycrcb[:, :, 0]
    cr = ycrcb[:, :, 1]
    cb = ycrcb[:, :, 2]
    m = ((cr >= 133) & (cr <= 180) & (cb >= 77) & (cb <= 135) & (y >= 35)).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, kernel, iterations=1)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel, iterations=1)
    return (m * 255).astype(np.uint8)


def _mediapipe_masks(rgb: np.ndarray, use_mediapipe: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    h, w = rgb.shape[:2]
    face = np.zeros((h, w), dtype=np.uint8)
    hands = np.zeros((h, w), dtype=np.uint8)
    fine = np.zeros((h, w), dtype=np.uint8)
    if not use_mediapipe:
        return face, hands, fine

    try:
        import mediapipe as mp  # type: ignore

        face_det = mp.solutions.face_detection.FaceDetection(model_selection=0, min_detection_confidence=0.5)
        hand_det = mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=2, min_detection_confidence=0.4)
        face_mesh = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=2, refine_landmarks=True)

        res_face = face_det.process(rgb)
        if res_face.detections:
            for det in res_face.detections:
                bb = det.location_data.relative_bounding_box
                x0 = int(max(0, bb.xmin * w))
                y0 = int(max(0, bb.ymin * h))
                x1 = int(min(w - 1, (bb.xmin + bb.width) * w))
                y1 = int(min(h - 1, (bb.ymin + bb.height) * h))
                if x1 > x0 and y1 > y0:
                    cx = (x0 + x1) // 2
                    cy = (y0 + y1) // 2
                    rx = max(4, (x1 - x0) // 2)
                    ry = max(4, (y1 - y0) // 2)
                    cv2.ellipse(face, (cx, cy), (rx, ry), 0, 0, 360, 255, -1)

        res_hands = hand_det.process(rgb)
        if res_hands.multi_hand_landmarks:
            for hand in res_hands.multi_hand_landmarks:
                pts = []
                for lm in hand.landmark:
                    x = int(np.clip(lm.x * w, 0, w - 1))
                    y = int(np.clip(lm.y * h, 0, h - 1))
                    pts.append((x, y))
                    cv2.circle(fine, (x, y), 2, 255, -1)
                hull = cv2.convexHull(np.array(pts, dtype=np.int32))
                cv2.fillConvexPoly(hands, hull, 255)

        mesh_res = face_mesh.process(rgb)
        if mesh_res.multi_face_landmarks:
            for mesh in mesh_res.multi_face_landmarks:
                pts = []
                for lm in mesh.landmark:
                    x = int(np.clip(lm.x * w, 0, w - 1))
                    y = int(np.clip(lm.y * h, 0, h - 1))
                    pts.append((x, y))
                hull = cv2.convexHull(np.array(pts, dtype=np.int32))
                cv2.fillConvexPoly(face, hull, 255)
                for idx in (33, 133, 362, 263, 1, 2, 5, 13, 14, 61, 291):
                    if idx < len(pts):
                        cv2.circle(fine, pts[idx], 3, 255, -1)
    except Exception:
        return face, hands, fine

    return face, hands, fine


def build_semantic_masks(rgb: np.ndarray, edge_strength: np.ndarray, cfg: SemanticConfig) -> SemanticMasks:
    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    face_cv = _face_mask(gray)
    skin = _skin_mask(rgb)
    saliency = _saliency_map(bgr)
    saliency_u8 = (saliency * 255.0).astype(np.uint8)

    face_mp, hands_mp, fine_mp = _mediapipe_masks(rgb, use_mediapipe=cfg.enabled and cfg.prefer_mediapipe)

    face = cv2.max(face_cv, face_mp)
    hands = hands_mp.copy()
    if not np.any(hands):
        hands = cv2.bitwise_and(skin, cv2.threshold((edge_strength * 255).astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
        hands = cv2.dilate(hands, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=1)

    fg_thr = float(np.percentile(saliency, 63.0))
    foreground = (saliency >= fg_thr).astype(np.uint8) * 255
    person = cv2.max(foreground, cv2.max(face, hands))

    if cfg.external_mask_path is not None and cfg.external_mask_path.exists():
        ext = cv2.imread(str(cfg.external_mask_path), cv2.IMREAD_GRAYSCALE)
        if ext is not None:
            ext = cv2.resize(ext, (w, h), interpolation=cv2.INTER_LINEAR)
            person = cv2.max(person, ext)

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hair = ((hsv[:, :, 2] < 120) & (hsv[:, :, 1] < 140) & (face > 0)).astype(np.uint8) * 255
    if not np.any(hair):
        hair = cv2.bitwise_and(cv2.dilate(face, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))), cv2.threshold(gray, 95, 255, cv2.THRESH_BINARY_INV)[1])

    clothing = cv2.subtract(person, cv2.max(skin, cv2.max(face, hands)))
    background = cv2.bitwise_not(cv2.threshold(person, 1, 255, cv2.THRESH_BINARY)[1])

    p1 = cv2.max(cv2.max(hands, fine_mp), cv2.bitwise_and(face, cv2.threshold((edge_strength * 255).astype(np.uint8), 180, 255, cv2.THRESH_BINARY)[1]))
    p2 = cv2.max(cv2.max(face, skin), cv2.max(hair, clothing))
    p3 = cv2.max(background, cv2.subtract(foreground, person))

    debug = np.zeros((h, w, 3), dtype=np.uint8)
    debug[p3 > 0] = (60, 60, 60)
    debug[background > 0] = (40, 70, 120)
    debug[clothing > 0] = (90, 180, 240)
    debug[hair > 0] = (120, 90, 20)
    debug[skin > 0] = (210, 160, 130)
    debug[face > 0] = (240, 180, 160)
    debug[hands > 0] = (250, 140, 120)
    debug[p1 > 0] = (255, 255, 255)

    return SemanticMasks(
        face=face,
        hands=hands,
        person=person,
        foreground=foreground,
        background=background,
        skin=skin,
        hair=hair,
        clothing=clothing,
        p1=p1,
        p2=p2,
        p3=p3,
        debug_rgb=debug,
    )
