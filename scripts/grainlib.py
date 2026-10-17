# -*- coding: utf-8 -*-
"""Algorithm library for grain-size analysis of SEM orientation-contrast images.

The pipeline is designed for images where grains differ mainly in brightness
(orientation contrast, e.g. ESD1), not for topographic surface images.  The
main entry point is :func:`segment_grains`; :func:`measure_grains` turns the
label image into per-grain records.

Calibration helpers read the ZEISS private TIFF tag 34118, or fall back to
detecting a scale bar in the bottom information strip.
"""
from __future__ import annotations

import re

import numpy as np
import cv2
from PIL import Image
from skimage.segmentation import watershed
from skimage.morphology import h_maxima, h_minima
from skimage.feature import peak_local_max
from scipy import ndimage as ndi


# --------------------------------------------------------------------- loading
def load_gray(path):
    """Read an image as an 8-bit grayscale array."""
    with Image.open(path) as image:
        arr = np.array(image)
    if arr.ndim == 3:
        rgb = arr[..., :3].astype(np.float64)
        arr = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    arr = arr.astype(np.float64)
    lo, hi = float(arr.min()), float(arr.max())
    if hi > lo and (hi > 255.0 or lo < 0.0):
        arr = (arr - lo) / (hi - lo) * 255.0
    return np.clip(arr, 0, 255).astype(np.uint8)


# ----------------------------------------------------------------- calibration
_NUMBER_RE = re.compile(r"^[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?$")


def _to_nm_per_px(value):
    """Convert a raw pixel-size value to nm/px, inferring the unit."""
    val = float(value)
    if not np.isfinite(val) or val <= 0:
        return None
    if val < 1e-3:          # metres
        return val * 1e9
    if val < 1.0:           # micrometres
        return val * 1e3
    return val              # nanometres


def _pixel_nm_from_text(text):
    """Parse ZEISS tag 34118.

    The tag is a long multi-line block.  Each acquisition frame starts with a
    frame index followed by seven numbers; the second number is the pixel size
    in metres:

        0
        8.588461e-09
        1.300000e+04
        6
        ...
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index in range(min(len(lines) - 1, 64)):
        first, second = lines[index], lines[index + 1]
        if not (_NUMBER_RE.match(first) and _NUMBER_RE.match(second)):
            continue
        frame = float(first)
        if frame != int(frame):
            continue
        nm = _to_nm_per_px(second)
        if nm is not None and 0.01 <= nm <= 10000.0:
            return nm
    return None


def tiff_pixel_nm(path):
    """Return (nm_per_px, description) from ZEISS private TIFF tag 34118.

    Different exporters store the tag either as a numeric sequence or as a
    multi-line text block; both layouts are handled.  ZEISS writes the pixel
    size in metres, other values may be micrometres or nanometres, so the unit
    is inferred from the magnitude.
    """
    try:
        with Image.open(path) as im:
            value = getattr(im, "tag_v2", {}).get(34118)
    except Exception as exc:  # pragma: no cover - damaged TIFFs
        return None, f"cannot read TIFF tags: {exc}"

    if value is None:
        return None, "TIFF tag 34118 not found"

    if isinstance(value, bytes):
        value = value.decode("ascii", "ignore")

    if isinstance(value, str):
        nm = _pixel_nm_from_text(value)
        if nm is None:
            return None, "tag 34118 has no parsable pixel size"
        return float(nm), "TIFF tag 34118"

    first = value[0] if isinstance(value, (tuple, list)) and len(value) else value
    try:
        nm = _to_nm_per_px(first)
    except Exception:
        text = first.decode("ascii", "ignore") if isinstance(first, bytes) else str(first)
        match = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)
        nm = _to_nm_per_px(match.group(0)) if match else None
    if nm is None or not (0.01 <= nm <= 10000.0):
        return None, f"invalid pixel size in tag 34118: {first!r}"
    return float(nm), "TIFF tag 34118"


def detect_info_bar(gray, dark_thr=60, min_frac=0.02, max_frac=0.25):
    """Return the first row of the bottom information strip, or 0 if absent.

    The strip is the contiguous block of dark rows at the bottom of the image.
    A couple of anti-aliased rows at the very bottom are tolerated.
    """
    height = gray.shape[0]
    # The median is robust to text and long bright ruler lines inside the strip,
    # which can push a row's mean well above the threshold.
    dark = np.median(gray, axis=1) < dark_thr

    i = height - 1
    while i >= 0 and not dark[i] and (height - 1 - i) < 3:
        i -= 1
    end = i
    while i >= 0 and dark[i]:
        i -= 1
    run = end - i

    if min_frac * height <= run <= max_frac * height:
        top = int(i + 1)
        # Information strips usually begin with a bright separator line; it is
        # part of the strip, not image content.  Include up to 4 such rows.
        added = 0
        while top > 0 and added < 4 and gray[top - 1].mean() > 200:
            top -= 1
            added += 1
        return top
    return 0


def _split_runs(columns):
    if len(columns) == 0:
        return []
    breaks = np.where(np.diff(columns) > 1)[0]
    return np.split(columns, breaks + 1)


def detect_scale_bar_px(gray, bar_top=None):
    """Detect the scale bar and return its length in pixels.

    Two instrument layouts are supported and must be ordered by a hard rule:
    a segmented horizontal line (FEI, text cuts the line into >= 2 pieces) wins
    over a continuous line with end ticks (ZEISS).  FEI strips also contain a
    longer frame line that passes the tick test, so mixing both candidates in
    one pool and sorting by length picks the wrong one.

    Returns a dict with ``px``, ``y``, ``x1``, ``x2``, ``n_segs`` and
    ``method``, or ``None``.
    """
    height, width = gray.shape
    if bar_top is None or bar_top <= 0:
        bar_top = detect_info_bar(gray)
    if bar_top <= 0:
        return None

    band_top = max(int(bar_top), height - int(0.20 * height))
    bright = gray[band_top:height, :] > 150
    fei_candidates, zeiss_candidates = [], []

    for y in range(bright.shape[0]):
        columns = np.where(bright[y])[0]
        if len(columns) < 15:
            continue
        runs = [r for r in _split_runs(columns) if len(r) >= 15]
        if not runs:
            continue

        # FEI: one bar broken into several collinear pieces by the value text.
        if 2 <= len(runs) <= 6:
            span = int(runs[-1][-1] - runs[0][0] + 1)
            gaps = [int(runs[k + 1][0] - runs[k][-1] - 1) for k in range(len(runs) - 1)]
            if 0.15 * width <= span <= 0.40 * width and max(gaps) <= 0.20 * width:
                fei_candidates.append(
                    (span, y + band_top, len(runs), int(runs[0][0]), int(runs[-1][-1]))
                )

        # ZEISS: one continuous line whose ends carry vertical ticks.
        for run in runs:
            length = int(run[-1] - run[0] + 1)
            if not (0.03 * width <= length <= 0.15 * width):
                continue
            x1, x2 = int(run[0]), int(run[-1])
            tick1 = int(bright[max(0, y - 12):y + 2, x1].sum())
            tick2 = int(bright[max(0, y - 12):y + 2, x2].sum())
            # The bar body contributes 1-3 px; end ticks add >= 8.
            if tick1 >= 8 and tick2 >= 8:
                zeiss_candidates.append((length, y + band_top, x1, x2))

    if fei_candidates:
        # Ignore frame lines that run into the image border.
        good = [c for c in fei_candidates if c[3] > 0.02 * width and c[4] < 0.98 * width]
        pool = good or fei_candidates
        pool.sort(key=lambda c: (-c[2], -c[0]))
        span, y, n_segs, x1, x2 = pool[0]
        return {"px": float(span), "y": int(y), "x1": x1, "x2": x2,
                "n_segs": int(n_segs), "method": "FEI-style segmented bar"}

    if zeiss_candidates:
        zeiss_candidates.sort(key=lambda c: -c[0])
        length, y, x1, x2 = zeiss_candidates[0]
        return {"px": float(length), "y": int(y), "x1": x1, "x2": x2,
                "n_segs": 1, "method": "ZEISS-style continuous bar"}

    return None


# ---------------------------------------------------------------- union-find
class UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[max(a, b)] = min(a, b)


class UFW(UF):
    """Union-find that also tracks a member weight."""

    def __init__(self, n):
        super().__init__(n)
        self.w = [1] * n

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a == b:
            return
        root, child = (a, b) if a < b else (b, a)
        self.p[child] = root
        self.w[root] += self.w[child]


# ---------------------------------------------------------------- relabelling
def compact(lab):
    lab = np.asarray(lab, np.int32)
    values, inverse = np.unique(lab[lab > 0], return_inverse=True)
    out = np.zeros_like(lab)
    out[lab > 0] = inverse + 1
    return out


def clean(lab, min_size):
    lab = np.asarray(lab, np.int32).copy()
    counts = np.bincount(lab.ravel())
    small = np.where(counts < min_size)[0]
    small = small[small > 0]
    if len(small):
        lab[np.isin(lab, small)] = 0
    return compact(lab)


# ---------------------------------------------------------------- merging
def merge_by_boundary(lab, gradient, threshold):
    """Merge adjacent regions whose shared boundary has a weak median gradient."""
    lab = np.asarray(lab, np.int32)
    height, width = lab.shape
    uf = UF(int(lab.max()) + 1)
    pairs = {}
    for dy, dx in ((0, 1), (1, 0)):
        a = lab[:height - dy, :width - dx]
        b = lab[dy:, dx:]
        grad = gradient[dy:, dx:]
        mask = (a > 0) & (b > 0) & (a != b)
        if not mask.any():
            continue
        aa, bb, gg = a[mask], b[mask], grad[mask]
        lo = np.minimum(aa, bb)
        hi = np.maximum(aa, bb)
        for left, right, value in zip(lo, hi, gg):
            pairs.setdefault((int(left), int(right)), []).append(value)
    for (left, right), values in pairs.items():
        if np.median(values) < threshold:
            uf.union(left, right)
    roots = np.array([uf.find(i) for i in range(int(lab.max()) + 1)])
    return compact(roots[lab])


def _iter_merge(lab, image, threshold, rounds):
    """Iteratively merge neighbours whose mean grey levels differ by < threshold."""
    lab = np.asarray(lab, np.int32).copy()
    height, width = lab.shape
    for _ in range(rounds):
        n = int(lab.max())
        if n == 0:
            break
        means = np.asarray(ndi.mean(image.astype(np.float32), labels=lab,
                                   index=np.arange(1, n + 1)))
        uf = UF(n + 1)
        for dy, dx in ((0, 1), (1, 0)):
            a = lab[:height - dy, :width - dx]
            b = lab[dy:, dx:]
            mask = (a > 0) & (b > 0) & (a != b)
            if not mask.any():
                continue
            aa, bb = a[mask], b[mask]
            lo = np.minimum(aa, bb)
            hi = np.maximum(aa, bb)
            diff = np.abs(means[lo - 1] - means[hi - 1])
            for left, right, value in zip(lo, hi, diff):
                if value < threshold:
                    uf.union(int(left), int(right))
        roots = np.array([uf.find(i) for i in range(n + 1)])
        new_lab = compact(roots[lab])
        if (new_lab == lab).all():
            lab = new_lab
            break
        lab = new_lab
    return lab


def merge_by_level(lab, image, threshold, rounds=6):
    return _iter_merge(lab, image, threshold, rounds)


def region_max_thickness(lab):
    """Max inscribed-circle radius (px) of every labelled region.

    The distance transform needs a zero source.  Using only the image frame is
    not enough: when the segmentation covers the whole image the transform
    returns FLT_MAX and every measured width becomes garbage.  Each region's
    own border is therefore used as a zero source, plus a 1 px outer frame.
    """
    lab = np.asarray(lab, np.int32)
    n = int(lab.max())
    if n == 0:
        return np.zeros(0, np.float32)

    foreground = lab > 0
    edge = cv2.morphologyEx(lab.astype(np.float32), cv2.MORPH_GRADIENT,
                            np.ones((3, 3), np.uint8)) > 0
    inner = foreground & (~edge)
    padded = np.pad(inner.astype(np.uint8), 1, mode="constant", constant_values=0)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, 5).astype(np.float32)[1:-1, 1:-1]
    out = np.zeros(n + 1, np.float32)
    np.maximum.at(out, lab[inner], distance[inner])
    return out[1:]


def remove_thin(lab, min_thick=2.5):
    """Dissolve regions thinner than ``min_thick`` px into their largest neighbour.

    Kept for exploratory use.  The production pipeline deliberately does *not*
    use this: merging an unresolvable sliver inflates its neighbour into a
    fictitious giant grain.
    """
    lab = np.asarray(lab, np.int32).copy()
    height, width = lab.shape
    while True:
        n = int(lab.max())
        if n == 0:
            break
        thick = region_max_thickness(lab)
        bad = set(np.where(thick < min_thick)[0] + 1)
        if not bad:
            break
        votes = {}
        for dy, dx in ((0, 1), (1, 0)):
            a = lab[:height - dy, :width - dx]
            b = lab[dy:, dx:]
            mask = (a > 0) & (b > 0) & (a != b)
            if not mask.any():
                continue
            for x, y in zip(a[mask], b[mask]):
                x, y = int(x), int(y)
                if x in bad or y in bad:
                    votes[(x, y)] = votes.get((x, y), 0) + 1
        merged = 0
        for (x, y), _ in sorted(votes.items(), key=lambda kv: -kv[1]):
            if x in bad and y in bad:
                target, source = (y, x) if thick[x - 1] <= thick[y - 1] else (x, y)
            elif x in bad:
                target, source = y, x
            elif y in bad:
                target, source = x, y
            else:
                continue
            if source not in bad:
                continue
            lab[lab == source] = target
            bad.discard(source)
            merged += 1
        if merged == 0:
            break
    return compact(lab)


# ---------------------------------------------------------------- noise
def noise_sigma(gray):
    """Robust noise level (grey levels) estimated from the NLM residual."""
    denoised = cv2.fastNlMeansDenoising(
        gray, None, h=10, templateWindowSize=7, searchWindowSize=21
    ).astype(np.float32)
    residual = gray.astype(np.float32) - denoised
    return float(1.4826 * np.median(np.abs(residual - np.median(residual))))


def merge_snr_track(lab, source, threshold, rounds=40):
    """Merge neighbours whose source-image means differ by < threshold."""
    lab = np.asarray(lab, np.int32).copy()
    n0 = int(lab.max())
    source64 = source.astype(np.float32)
    size = np.ones(n0 + 1, np.int64)
    size[0] = 0
    height, width = lab.shape
    for _ in range(rounds):
        n = int(lab.max())
        if n == 0:
            break
        means = np.asarray(ndi.mean(source64, labels=lab, index=np.arange(1, n + 1)))
        uf = UFW(n + 1)
        uf.w = [int(v) for v in size[:n + 1]]
        for dy, dx in ((0, 1), (1, 0)):
            a = lab[:height - dy, :width - dx]
            b = lab[dy:, dx:]
            mask = (a > 0) & (b > 0) & (a != b)
            if not mask.any():
                continue
            aa, bb = a[mask], b[mask]
            lo = np.minimum(aa, bb)
            hi = np.maximum(aa, bb)
            diff = np.abs(means[lo - 1] - means[hi - 1])
            for left, right, value in zip(lo, hi, diff):
                if value < threshold:
                    uf.union(int(left), int(right))
        roots = np.array([uf.find(i) for i in range(n + 1)], np.int32)
        unique = np.unique(roots[1:])
        remap = np.zeros(n + 1, np.int32)
        new_size = np.zeros(len(unique) + 1, np.int64)
        for k, root in enumerate(unique, 1):
            remap[root] = k
            new_size[k] = uf.w[root]
        new_lab = remap[roots][lab]
        size = new_size
        if (new_lab == lab).all():
            lab = new_lab
            break
        lab = new_lab
    lab = compact(lab)
    members = np.zeros(int(lab.max()) + 1, np.int64)
    members[1:len(size)] = size[1:len(size)]
    return lab, members


# ---------------------------------------------------------------- pipeline
def enhance(gray, nlm=10, clip=2.0, grid=8):
    """Denoise + CLAHE + unsharp mask, for display only."""
    denoised = cv2.fastNlMeansDenoising(
        gray, None, h=nlm, templateWindowSize=7, searchWindowSize=21
    )
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(grid, grid)).apply(denoised)
    blurred = cv2.GaussianBlur(clahe, (0, 0), 1.5)
    return cv2.addWeighted(clahe, 1.5, blurred, -0.5, 0)


def segment_grains(gray, pixel_nm, *, nlm=10, clahe_clip=2.0, clahe_grid=8,
                   mean_shift_sp=10, mean_shift_sr=12, seed_h=2,
                   merge_grad=3.0, thin_px=3.0, min_size=80,
                   max_diam_nm=1500.0):
    """Run the full grain segmentation pipeline.

    Returns ``(labels, plateau_image, stats)``.  ``stats`` carries the noise
    level, the fraction of area discarded as unresolvable slivers or giants,
    and the fraction of the field that ended up analysed.
    """
    sigma = noise_sigma(gray)

    denoised = cv2.fastNlMeansDenoising(
        gray, None, h=nlm, templateWindowSize=7, searchWindowSize=21
    )
    clahe = cv2.createCLAHE(clipLimit=clahe_clip,
                            tileGridSize=(clahe_grid, clahe_grid)).apply(denoised)
    clahe = cv2.medianBlur(clahe, 3)
    shifted = cv2.pyrMeanShiftFiltering(
        cv2.cvtColor(clahe, cv2.COLOR_GRAY2BGR),
        sp=mean_shift_sp, sr=mean_shift_sr, maxLevel=1,
    )
    plateau = cv2.cvtColor(shifted, cv2.COLOR_BGR2GRAY)

    gradient = cv2.morphologyEx(
        plateau, cv2.MORPH_GRADIENT,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )
    # Union of h-maxima and h-minima: dark grains are missed if only maxima
    # are used as watershed seeds.
    seeds = h_maxima(plateau, seed_h) | h_minima(plateau, seed_h)
    markers, _ = ndi.label(seeds)
    labels = watershed(gradient, markers)

    if merge_grad > 0:
        labels = merge_by_boundary(labels, gradient, merge_grad)
    covered = int((labels > 0).sum())

    # Unresolvable slivers are set to zero, never merged into a neighbour.
    # Merging them would fuse whole fine-structured areas into a fictitious
    # 5-7 um grain that dominates the statistics.
    thickness = region_max_thickness(labels)
    thin_ids = np.where(2.0 * thickness < thin_px)[0] + 1
    thin_area = 0
    if len(thin_ids):
        thin_mask = np.isin(labels, thin_ids)
        thin_area = int(thin_mask.sum())
        labels = np.where(thin_mask, 0, labels).astype(np.int32)
    labels = clean(compact(labels), min_size)

    # Patches larger than any plausible grain are connected unresolvable
    # substructure, not grains.
    giant_area = 0
    n = int(labels.max())
    if n:
        areas = np.bincount(labels.ravel(), minlength=n + 1)[1:]
        diameters = 2.0 * np.sqrt(areas / np.pi) * pixel_nm
        bad = np.where(diameters > max_diam_nm)[0] + 1
        if len(bad):
            bad_mask = np.isin(labels, bad)
            giant_area = int(bad_mask.sum())
            labels = np.where(bad_mask, 0, labels).astype(np.int32)
        labels = clean(compact(labels), min_size)

    stats = {
        "noise_sigma": round(sigma, 2),
        "thin_frac": round(thin_area / covered, 3) if covered else 0.0,
        "giant_frac": round(giant_area / covered, 3) if covered else 0.0,
        "analysed_area_frac": round(float((labels > 0).mean()), 3),
    }
    return labels, plateau, stats


def segment_final(gray, pixel_nm, **kwargs):
    """Backward-compatible wrapper around :func:`segment_grains`."""
    labels, plateau, _ = segment_grains(gray, pixel_nm, **kwargs)
    return labels, plateau, noise_sigma(gray)


# ---------------------------------------------------------------- measurement
def equivalent_diameters_nm(labels, pixel_nm):
    areas = np.bincount(np.asarray(labels).ravel())[1:]
    areas = areas[areas > 0]
    return 2.0 * np.sqrt(areas / np.pi) * pixel_nm


def measure_grains(labels, gray, pixel_nm, border=5):
    """Turn a label image into one record per grain."""
    height, width = labels.shape
    objects = ndi.find_objects(labels)
    thickness = region_max_thickness(labels) * 2.0 * pixel_nm
    records = []

    for index, sl in enumerate(objects, 1):
        if sl is None:
            continue
        mask = labels[sl] == index
        area = int(mask.sum())
        if area == 0:
            continue

        ys, xs = sl
        yy, xx = np.nonzero(mask)
        yy = yy + ys.start
        xx = xx + xs.start

        eq = 2.0 * np.sqrt(area / np.pi) * pixel_nm
        cy, cx = float(yy.mean()), float(xx.mean())
        mxx = float(np.mean((xx - cx) ** 2))
        myy = float(np.mean((yy - cy) ** 2))
        mxy = float(np.mean((xx - cx) * (yy - cy)))
        eigenvalues = np.linalg.eigvalsh(np.array([[mxx, mxy], [mxy, myy]]))
        major = 4.0 * np.sqrt(max(eigenvalues[1], 0.0)) * pixel_nm
        minor = 4.0 * np.sqrt(max(eigenvalues[0], 0.0)) * pixel_nm

        touches_border = int(
            ys.start <= border or xs.start <= border
            or ys.stop >= height - border or xs.stop >= width - border
        )
        grey = gray[sl][mask]
        records.append({
            "id": index,
            "area_px": area,
            "eq_diam_nm": round(eq, 1),
            "major_nm": round(major, 1),
            "minor_nm": round(minor, 1),
            "width_nm": round(float(thickness[index - 1]), 1),
            "aspect": round(major / max(minor, 1e-6), 2),
            "touches_border": touches_border,
            "grey_mean": round(float(grey.mean()), 1),
            "grey_std": round(float(grey.std()), 1),
        })
    return records


# ---------------------------------------------------------------- visualisation
def overlay(gray, labels, text=None, color=(0, 0, 255)):
    edge = cv2.morphologyEx(labels.astype(np.float32), cv2.MORPH_GRADIENT,
                            np.ones((3, 3), np.uint8)) > 0
    base = gray if gray.ndim == 3 else cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    canvas = base.copy()
    canvas[edge] = color
    if text:
        cv2.putText(canvas, text, (10, 32), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (0, 255, 255), 2)
    return canvas


def colorize(labels, seed=7):
    n = int(labels.max())
    rng = np.random.default_rng(seed)
    hsv = np.zeros((n + 1, 3), np.uint8)
    if n:
        hsv[1:, 0] = rng.integers(0, 180, n)
        hsv[1:, 1] = rng.integers(90, 200, n)
        hsv[1:, 2] = rng.integers(180, 255, n)
    return cv2.cvtColor(hsv.reshape(-1, 1, 3), cv2.COLOR_HSV2BGR).reshape(-1, 3)[labels]


# ---------------------------------------------------------------- clusters
def detect_clusters(gray, pixel_nm, *, nlm=10, tophat_ksize=31,
                    smooth_sigma=2.0, min_distance=17, k_sigma=2.0):
    """Count bright spherical clusters on a surface image.

    Top-hat -> Gaussian -> local maxima.  This is *not* a grain measurement:
    on surface views the spheres are growth features, often 1-2 orders of
    magnitude larger than the grains inside them.  The returned diameter is
    only an equivalent spacing based on total area / count.

    Returns ``(peaks, equivalent_diameter_nm, hillshade)`` where ``peaks`` is
    an (N, 2) array of (row, column).
    """
    denoised = cv2.fastNlMeansDenoising(
        gray, None, h=nlm, templateWindowSize=7, searchWindowSize=21
    )
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (tophat_ksize, tophat_ksize)
    )
    tophat = cv2.morphologyEx(denoised, cv2.MORPH_TOPHAT, kernel)
    smoothed = cv2.GaussianBlur(tophat, (0, 0), smooth_sigma)
    threshold = float(smoothed.mean() + k_sigma * smoothed.std())
    peaks = peak_local_max(
        smoothed, min_distance=min_distance,
        threshold_abs=threshold, exclude_border=False,
    )
    count = max(len(peaks), 1)
    area_nm2 = gray.size * pixel_nm ** 2
    equivalent = 2.0 * np.sqrt(area_nm2 / count / np.pi)
    return peaks, equivalent, smoothed
