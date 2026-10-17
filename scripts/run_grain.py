#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Command-line grain-size analysis for SEM orientation-contrast images.

Examples
--------
    python run_grain.py --input ./images --output ./results
    python run_grain.py -i ./images --nm-per-px 8.26
    python run_grain.py -i ./images --bar-um 1.0
    python run_grain.py -i ./surface_images --mode cluster
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grainlib  # noqa: E402

BORDER = 5
DEFAULT_PATTERNS = ("*.tif", "*.tiff", "*.png", "*.bmp", "*.jpg", "*.jpeg")
OUT_SUBDIRS = {
    "enhanced": "01_enhanced",
    "plateaus": "02_plateaus",
    "overlay": "03_overlay",
    "colored": "04_colored",
    "csv": "05_csv",
    "charts": "06_charts",
}


class CalibrationError(RuntimeError):
    pass


# --------------------------------------------------------------------- helpers
def safe_stem(path):
    stem = Path(path).stem
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).strip() or "image"


def find_images(input_path, patterns, recursive=False, exclude=None):
    path = Path(input_path)
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"input not found: {input_path}")

    found = []
    for pattern in patterns:
        iterator = path.rglob(pattern) if recursive else path.glob(pattern)
        for item in iterator:
            if not item.is_file():
                continue
            if exclude and (exclude in item.parents or item.parent == exclude):
                continue
            found.append(item)
    return sorted(set(found), key=lambda p: str(p).lower())


def calibrate(path, original, args):
    """Resolve nm/px with a strict order: explicit > TIFF tag > scale bar > HFW."""
    if args.nm_per_px is not None:
        if args.nm_per_px <= 0:
            raise CalibrationError("--nm-per-px must be positive")
        return float(args.nm_per_px), "explicit --nm-per-px"

    nm, note = grainlib.tiff_pixel_nm(path)
    if nm is not None and 0.01 <= nm <= 10000.0:
        return float(nm), note

    if args.bar_um:
        bar = grainlib.detect_scale_bar_px(original)
        if bar:
            nm = args.bar_um * 1000.0 / bar["px"]
            return float(nm), (
                f"scale bar: {bar['px']:.1f} px = {args.bar_um:g} um "
                f"({bar['method']})"
            )

    if args.hfw_um:
        nm = args.hfw_um * 1000.0 / original.shape[1]
        return float(nm), f"HFW {args.hfw_um:g} um / {original.shape[1]} px"

    raise CalibrationError(
        "cannot calibrate: TIFF tag 34118 absent; pass --nm-per-px, "
        "--bar-um (with a detectable bar) or --hfw-um"
    )


def _stats(values):
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return dict(mean=float("nan"), median=float("nan"), std=float("nan"),
                    d10=float("nan"), d90=float("nan"))
    return dict(
        mean=float(values.mean()),
        median=float(np.median(values)),
        std=float(values.std(ddof=1)) if values.size > 1 else 0.0,
        d10=float(np.percentile(values, 10)),
        d90=float(np.percentile(values, 90)),
    )


def _write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _save_png(path, array_bgr):
    Image.fromarray(array_bgr[..., ::-1]).save(path)


# --------------------------------------------------------------------- grains
def process_grains(path, outroot, args):
    original = grainlib.load_gray(path)
    bar_top = 0 if args.no_info_bar else grainlib.detect_info_bar(original)
    work = original[:bar_top, :] if bar_top else original

    if min(work.shape) < 32:
        raise RuntimeError(f"image too small after cropping the info bar: {work.shape}")

    pixel_nm, calibration = calibrate(path, original, args)
    stem = safe_stem(path)

    labels, plateau, stats = grainlib.segment_grains(
        work, pixel_nm,
        nlm=args.nlm,
        clahe_clip=args.clahe_clip,
        clahe_grid=args.clahe_grid,
        mean_shift_sp=args.mean_shift_sp,
        mean_shift_sr=args.mean_shift_sr,
        seed_h=args.seed_h,
        merge_grad=args.merge_grad,
        thin_px=args.thin_px,
        min_size=args.min_size,
        max_diam_nm=args.max_diam_nm,
    )

    border = max(0, args.border)
    if border:
        labels[:border, :] = 0
        labels[-border:, :] = 0
        labels[:, :border] = 0
        labels[:, -border:] = 0
    labels = grainlib.clean(labels, args.min_size)

    if int(labels.max()) == 0:
        raise RuntimeError("segmentation produced no grains (check the image type/contrast)")

    enhanced = grainlib.enhance(work, nlm=args.nlm,
                                clip=args.clahe_clip, grid=args.clahe_grid)

    Image.fromarray(enhanced).save(
        outroot / OUT_SUBDIRS["enhanced"] / f"{stem}_enhanced.png")
    Image.fromarray(plateau).save(
        outroot / OUT_SUBDIRS["plateaus"] / f"{stem}_plateaus.png")
    _save_png(outroot / OUT_SUBDIRS["overlay"] / f"{stem}_overlay.png",
              grainlib.overlay(enhanced, labels))
    colored = grainlib.colorize(labels, seed=args.seed)
    background = np.repeat(enhanced[..., None], 3, axis=2)
    colored[labels == 0] = background[labels == 0]
    _save_png(outroot / OUT_SUBDIRS["colored"] / f"{stem}_colored.png", colored)

    records = grainlib.measure_grains(labels, work, pixel_nm, border=border)
    _write_csv(
        outroot / OUT_SUBDIRS["csv"] / f"{stem}_grains.csv",
        list(records[0].keys()), records,
    )

    diameters = np.array([r["eq_diam_nm"] for r in records], dtype=float)
    interior = np.array([r["eq_diam_nm"] for r in records if not r["touches_border"]],
                        dtype=float)

    warnings = []
    used = interior if interior.size else diameters
    if not interior.size:
        warnings.append("all grains touch the border; interior-only statistics unavailable")
    if stats["thin_frac"] > args.thin_warn:
        warnings.append(
            f"unresolvable slivers = {stats['thin_frac']:.0%} of the segmented area"
        )
    if stats["analysed_area_frac"] < args.area_warn:
        warnings.append(
            f"only {stats['analysed_area_frac']:.0%} of the field was analysed"
        )
    if stats["noise_sigma"] > args.noise_warn:
        warnings.append(
            f"noise sigma = {stats['noise_sigma']:.1f} grey levels (weak contrast)"
        )
    if used.size < args.min_grains:
        warnings.append(f"only {used.size} grains measured (small sample)")

    all_stats = _stats(diameters)
    interior_stats = _stats(used)

    row = {
        "sample": stem,
        "file": str(path),
        "n": int(diameters.size),
        "n_interior": int(interior.size),
        "mean_nm": round(all_stats["mean"], 1),
        "median_nm": round(all_stats["median"], 1),
        "std_nm": round(all_stats["std"], 1),
        "d10_nm": round(all_stats["d10"], 1),
        "d90_nm": round(all_stats["d90"], 1),
        "mean_int_nm": round(interior_stats["mean"], 1),
        "median_int_nm": round(interior_stats["median"], 1),
        "analysed_area_frac": stats["analysed_area_frac"],
        "thin_frac": stats["thin_frac"],
        "giant_frac": stats["giant_frac"],
        "noise_sigma": stats["noise_sigma"],
        "pixel_nm": round(pixel_nm, 4),
        "info_bar_rows": int(bar_top),
        "calibration": calibration,
        "warnings": "; ".join(warnings),
    }

    print(
        f"{stem}: n={diameters.size} interior={interior.size} "
        f"median={interior_stats['median']:.0f} nm mean={interior_stats['mean']:.0f} nm "
        f"covered={stats['analysed_area_frac']:.2f} "
        f"({pixel_nm:.3f} nm/px, {calibration})"
    )
    return row, {"all": diameters.tolist(), "interior": used.tolist()}


# -------------------------------------------------------------------- clusters
def process_clusters(path, outroot, args):
    original = grainlib.load_gray(path)
    bar_top = 0 if args.no_info_bar else grainlib.detect_info_bar(original)
    work = original[:bar_top, :] if bar_top else original
    pixel_nm, calibration = calibrate(path, original, args)
    stem = safe_stem(path)

    peaks, equivalent, smoothed = grainlib.detect_clusters(
        work, pixel_nm,
        nlm=args.nlm,
        tophat_ksize=args.tophat_ksize,
        smooth_sigma=args.smooth_sigma,
        min_distance=args.min_distance,
        k_sigma=args.k_sigma,
    )

    marked = np.repeat(work[..., None], 3, axis=2)
    for row, column in peaks:
        marked[int(row), int(column)] = (0, 0, 255)
    _save_png(outroot / OUT_SUBDIRS["overlay"] / f"{stem}_cluster_marks.png", marked)
    Image.fromarray(smoothed).save(
        outroot / OUT_SUBDIRS["plateaus"] / f"{stem}_tophat.png")

    records = [{
        "id": index,
        "row_px": int(row),
        "col_px": int(column),
        "row_nm": round(int(row) * pixel_nm, 1),
        "col_nm": round(int(column) * pixel_nm, 1),
    } for index, (row, column) in enumerate(peaks, 1)]
    _write_csv(
        outroot / OUT_SUBDIRS["csv"] / f"{stem}_clusters.csv",
        ["id", "row_px", "col_px", "row_nm", "col_nm"],
        records,
    )

    warnings = []
    if len(peaks) < args.min_grains:
        warnings.append(f"only {len(peaks)} clusters detected")
    if len(peaks) == 0:
        warnings.append("no clusters detected; adjust --k-sigma or --min-distance")

    print(f"{stem}: clusters={len(peaks)} equivalent_diameter={equivalent:.0f} nm "
          f"({pixel_nm:.3f} nm/px, {calibration})")
    return {
        "sample": stem,
        "file": str(path),
        "n_clusters": len(peaks),
        "equiv_diam_nm": round(equivalent, 1),
        "pixel_nm": round(pixel_nm, 4),
        "calibration": calibration,
        "warnings": "; ".join(warnings),
    }


# ----------------------------------------------------------------------- report
def write_report(outroot, rows, args, calibration_rows):
    english = args.report_lang == "en"
    lines = []

    if args.mode == "cluster":
        if english:
            lines += ["# Cluster analysis report", "",
                      f"Generated: {_dt.datetime.now():%Y-%m-%d %H:%M}", "",
                      "## Calibration", "", "| Sample | nm/px | Source |", "|---|---|---|"]
        else:
            lines += ["# 团簇分析报告", "",
                      f"生成时间：{_dt.datetime.now():%Y-%m-%d %H:%M}", "",
                      "## 标定", "", "| 样品 | nm/px | 来源 |", "|---|---|---|"]
        for row in calibration_rows:
            lines.append(f"| {row['sample']} | {row['pixel_nm']:.4f} | {row['calibration']} |")

        if english:
            lines += ["", "## Results", "",
                      "| Sample | clusters | equivalent spacing (nm) |", "|---|---|---|"]
        else:
            lines += ["", "## 结果", "",
                      "| 样品 | 团簇数 | 等效间距 (nm) |", "|---|---|---|"]
        for row in rows:
            lines.append(f"| {row['sample']} | {row['n_clusters']} | {row['equiv_diam_nm']:.0f} |")

        if english:
            lines += ["", "## Notes", "",
                      "1. These are bright growth clusters on a surface image, **not grains**.",
                      "2. The equivalent spacing is total area / count; it is not a measured cluster diameter.",
                      "3. Open `03_overlay/*_cluster_marks.png` and check that one marker sits on each cluster."]
        else:
            lines += ["", "## 注意事项", "",
                      "1. 这是表面亮团簇，**不是晶粒**。",
                      "2. 等效间距按总面积/个数折算，不是逐颗实测直径。",
                      "3. 请打开 `03_overlay/*_cluster_marks.png`，核对每个团簇都有一个标记点。"]
    else:
        if english:
            lines += ["# Grain-size analysis report", "",
                      f"Generated: {_dt.datetime.now():%Y-%m-%d %H:%M}", "",
                      "## Calibration", "", "| Sample | nm/px | Source |", "|---|---|---|"]
        else:
            lines += ["# 晶粒尺寸分析报告", "",
                      f"生成时间：{_dt.datetime.now():%Y-%m-%d %H:%M}", "",
                      "## 标定", "", "| 样品 | nm/px | 来源 |", "|---|---|---|"]
        for row in calibration_rows:
            lines.append(f"| {row['sample']} | {row['pixel_nm']:.4f} | {row['calibration']} |")

        if english:
            lines += ["", "## Results (interior grains only)", "",
                      "| Sample | n | mean (nm) | median (nm) | d10 | d90 | analysed area |",
                      "|---|---|---|---|---|---|---|"]
        else:
            lines += ["", "## 结果（仅统计不接触图像边缘的晶粒）", "",
                      "| 样品 | 晶粒数 | 平均 (nm) | 中位 (nm) | d10 | d90 | 已分析面积 |",
                      "|---|---|---|---|---|---|---|"]
        for row in rows:
            lines.append(
                f"| {row['sample']} | {row['n_interior']} | {row['mean_int_nm']:.0f} | "
                f"{row['median_int_nm']:.0f} | {row['d10_nm']:.0f} | {row['d90_nm']:.0f} | "
                f"{row['analysed_area_frac']:.0%} |"
            )

        if english:
            lines += ["", "## Notes", "",
                      "1. Resolvable limit is about 3-4 px; structures below it are rejected, so the median is a conservative (high) estimate.",
                      "2. This is semi-automatic segmentation: open `03_overlay/*.png` and check that red boundaries follow grey-level steps.",
                      "3. Orientation-contrast images with weak contrast have lower absolute reliability.",
                      "4. Surface clusters are growth features, not grains; use `--mode cluster` separately and do not compare them with grain sizes."]
        else:
            lines += ["", "## 注意事项", "",
                      "1. 可分辨下限约 3–4 px，低于此的结构已剔除，因此中位粒径是**偏保守（偏大）的下限估计**。",
                      "2. 分割是半自动的：请打开 `03_overlay/*.png` 目视核对，红色边界应贴合灰度台阶。",
                      "3. 取向衬度弱的图绝对数值可信度较低，跨样品比较需谨慎。",
                      "4. 表面球状团簇是生长形貌、不是晶粒，请用 `--mode cluster` 单独统计，不要与晶粒尺寸混用。"]

    flagged = [r for r in rows if r.get("warnings")]
    if flagged:
        lines += ["", "## Warnings" if english else "## 警告", ""]
        for row in flagged:
            lines.append(f"- **{row['sample']}**: {row['warnings']}")

    (outroot / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------- CLI
def build_parser():
    parser = argparse.ArgumentParser(
        description="Grain-size statistics for SEM orientation-contrast images."
    )
    parser.add_argument("--input", "-i", required=True,
                        help="image file or directory")
    parser.add_argument("--output", "-o", default=None,
                        help="output directory (default: <input>/grain_size_<timestamp>)")
    parser.add_argument("--pattern", default=None,
                        help="comma-separated glob patterns (default: common image extensions)")
    parser.add_argument("--recursive", action="store_true",
                        help="search input directory recursively")

    calibration = parser.add_argument_group("calibration")
    calibration.add_argument("--nm-per-px", type=float, default=None,
                             help="override for every image")
    calibration.add_argument("--bar-um", type=float, default=None,
                             help="nominal scale-bar length in um (bar is detected automatically)")
    calibration.add_argument("--hfw-um", type=float, default=None,
                             help="horizontal field width in um")
    calibration.add_argument("--no-info-bar", action="store_true",
                             help="do not crop the bottom information strip")

    parser.add_argument("--mode", choices=("grains", "cluster"), default="grains",
                        help="grains: watershed grain statistics; cluster: bright-sphere counting")

    options = parser.add_argument_group("segmentation")
    options.add_argument("--border", type=int, default=BORDER,
                         help="width of the border ring excluded from grain statistics")
    options.add_argument("--nlm", type=float, default=10.0)
    options.add_argument("--clahe-clip", type=float, default=2.0)
    options.add_argument("--clahe-grid", type=int, default=8)
    options.add_argument("--mean-shift-sp", type=int, default=10)
    options.add_argument("--mean-shift-sr", type=int, default=12)
    options.add_argument("--seed-h", type=int, default=2)
    options.add_argument("--merge-grad", type=float, default=3.0)
    options.add_argument("--thin-px", type=float, default=3.0)
    options.add_argument("--min-size", type=int, default=80)
    options.add_argument("--max-diam-nm", type=float, default=1500.0)

    cluster = parser.add_argument_group("cluster mode")
    cluster.add_argument("--tophat-ksize", type=int, default=31)
    cluster.add_argument("--smooth-sigma", type=float, default=2.0)
    cluster.add_argument("--min-distance", type=int, default=17)
    cluster.add_argument("--k-sigma", type=float, default=2.0)

    checks = parser.add_argument_group("quality checks")
    checks.add_argument("--thin-warn", type=float, default=0.15)
    checks.add_argument("--area-warn", type=float, default=0.50)
    checks.add_argument("--noise-warn", type=float, default=6.0)
    checks.add_argument("--min-grains", type=int, default=30)

    parser.add_argument("--seed", type=int, default=7, help="colour random seed")
    parser.add_argument("--no-plots", action="store_true")
    parser.add_argument("--report-lang", choices=("zh", "en"), default="zh")
    parser.add_argument("--skip-uncalibrated", action="store_true",
                        help="skip images that cannot be calibrated instead of aborting")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    patterns = (tuple(p.strip() for p in args.pattern.split(",") if p.strip())
                if args.pattern else DEFAULT_PATTERNS)

    input_path = Path(args.input).expanduser().resolve()
    output = (Path(args.output).expanduser().resolve() if args.output else None)
    if output is None:
        base = input_path if input_path.is_dir() else input_path.parent
        output = base / f"grain_size_{_dt.datetime.now():%Y%m%d_%H%M%S}"

    images = find_images(input_path, patterns, args.recursive,
                         exclude=output if output.exists() else None)
    if not images:
        print(f"error: no images matched {patterns} under {input_path}", file=sys.stderr)
        return 2

    output.mkdir(parents=True, exist_ok=True)
    for sub in OUT_SUBDIRS.values():
        (output / sub).mkdir(parents=True, exist_ok=True)

    rows, series, failures = [], {}, []
    for path in images:
        try:
            if args.mode == "cluster":
                rows.append(process_clusters(path, output, args))
            else:
                row, diameters = process_grains(path, output, args)
                rows.append(row)
                series[row["sample"]] = diameters
        except CalibrationError as exc:
            if args.skip_uncalibrated:
                print(f"skip {path.name}: {exc}", file=sys.stderr)
                failures.append((path.name, str(exc)))
                continue
            print(f"error: {path.name}: {exc}", file=sys.stderr)
            print("hint: pass --nm-per-px, or --bar-um together with a visible scale bar",
                  file=sys.stderr)
            return 3
        except Exception as exc:
            print(f"error: {path.name}: {exc}", file=sys.stderr)
            failures.append((path.name, str(exc)))
            if not args.skip_uncalibrated:
                return 4

    if not rows:
        print("error: nothing was analysed", file=sys.stderr)
        return 4

    if args.mode == "grains":
        fieldnames = list(rows[0].keys())
        _write_csv(output / OUT_SUBDIRS["csv"] / "summary.csv", fieldnames, rows)
        (output / OUT_SUBDIRS["csv"] / "_diameters.json").write_text(
            json.dumps(series, indent=1), encoding="utf-8")
        if not args.no_plots:
            try:
                import plots
                plots.make_charts(output, lang=args.report_lang)
            except Exception as exc:  # charts are optional
                print(f"warning: could not draw charts: {exc}", file=sys.stderr)
    else:
        _write_csv(output / OUT_SUBDIRS["csv"] / "summary.csv",
                   list(rows[0].keys()), rows)

    write_report(output, rows, args, rows)
    if failures:
        (output / "failures.txt").write_text(
            "\n".join(f"{name}\t{reason}" for name, reason in failures),
            encoding="utf-8")

    print(f"\nDone: {len(rows)} image(s) -> {output}")
    print(f"Open {output / OUT_SUBDIRS['overlay']} and check the boundaries visually.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
