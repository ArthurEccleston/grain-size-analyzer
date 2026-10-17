# -*- coding: utf-8 -*-
"""Generate synthetic SEM-like demo images.

The demo images contain no real experimental data, so they are safe to publish
with the repository.  They are only meant to exercise the pipeline, not to
validate measurement accuracy.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy.spatial import cKDTree


def make_grain_image(path, width=1024, height=768, n_seeds=300,
                     noise=3.0, info_bar=True, seed=3):
    """Write a Voronoi-cell image resembling orientation contrast."""
    rng = np.random.default_rng(seed)
    content_h = height - (60 if info_bar else 0)

    yy, xx = np.mgrid[0:content_h, 0:width]
    points = rng.uniform([0, 0], [width, content_h], size=(n_seeds, 2))
    tree = cKDTree(points)
    _, index = tree.query(np.column_stack([xx.ravel(), yy.ravel()]))
    labels = index.reshape(content_h, width)

    levels = rng.integers(75, 175, n_seeds).astype(np.float32)
    image = levels[labels]
    image += cv2.GaussianBlur(
        rng.normal(0, 18, (content_h, width)).astype(np.float32), (0, 0), 25)
    image += rng.normal(0, noise, image.shape).astype(np.float32)
    image = np.clip(image, 0, 255).astype(np.uint8)

    if info_bar:
        strip = np.full((height - content_h, width), 35, np.uint8)
        image = np.vstack([image, strip])
        bar_y = height - 28
        x1, x2 = 100, 225          # 125 px = 1 um at 8.0 nm/px
        image[bar_y, x1:x2 + 1] = 220
        image[bar_y - 10:bar_y + 1, x1] = 220
        image[bar_y - 10:bar_y + 1, x2] = 220

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(path)
    return path


def make_cluster_image(path, width=1024, height=768, n_clusters=220,
                       radius=14, noise=2.0, info_bar=True, seed=5):
    """Write a surface-like image with bright spherical clusters."""
    rng = np.random.default_rng(seed)
    content_h = height - (60 if info_bar else 0)
    image = np.full((content_h, width), 55, np.uint8)

    for _ in range(n_clusters):
        cy = int(rng.integers(radius, content_h - radius))
        cx = int(rng.integers(radius, width - radius))
        value = int(rng.integers(140, 230))
        cv2.circle(image, (cx, cy), int(radius), value, -1)
    image = cv2.GaussianBlur(image, (0, 0), 4.0).astype(np.float32)
    image += cv2.GaussianBlur(
        rng.normal(0, 15, image.shape).astype(np.float32), (0, 0), 30)
    image += rng.normal(0, noise, image.shape).astype(np.float32)
    image = np.clip(image, 0, 255).astype(np.uint8)

    if info_bar:
        strip = np.full((height - content_h, width), 35, np.uint8)
        image = np.vstack([image, strip])

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(path)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create synthetic demo images.")
    parser.add_argument("--output", "-o", default="examples/demo_input")
    args = parser.parse_args(argv)

    out = Path(args.output)
    grain = make_grain_image(out / "demo_grains.tif")
    cluster = make_cluster_image(out / "demo_clusters.tif")
    print(f"written: {grain}")
    print(f"written: {cluster}")
    print("grain demo calibration: 8.0 nm/px (use --nm-per-px 8.0, or --bar-um 1.0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
