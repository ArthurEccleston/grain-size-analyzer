---
name: grain-size
description: Statistical grain-size analysis for SEM orientation-contrast images (ESD1 and similar). Use when the user asks to 统计晶粒尺寸 / 粒径统计 / 晶粒大小分析 / 算等效圆直径 / measure grain size on SEM images, or wants a folder of ZEISS/FEI TIFF images turned into grain-size statistics and charts. Calibrates nm/px from TIFF tag 34118, a detected scale bar, or an explicit value; exports per-grain CSV, overlay/coloured images and distribution charts. Do not use for surface topography images — bright spherical surface clusters must use --mode cluster.
---

# Grain-size analysis

Scripts live next to this file in `scripts/`. Run them with a Python that has
`requirements.txt` installed (Python 3.10–3.13; OpenCV must be the headless
build).

## 1. Before running

Confirm with the user:

1. **Input** — a file or folder of images. Default patterns: `*.tif,*.tiff,*.png,*.bmp,*.jpg,*.jpeg`.
2. **Calibration** — one of:
   - the TIFF carries ZEISS private tag 34118 (read automatically);
   - the scale-bar's nominal length is known (`--bar-um 1.0`) and the bar is visible in the image;
   - the horizontal field width is known (`--hfw-um 20.7`);
   - a single nm/px value applies to every image (`--nm-per-px 8.26`).

**Never guess nm/px.** If none of the four is available, stop and ask. A wrong
calibration silently scales every reported number.

3. **Image type** — grains mode only makes sense when grains differ in
   brightness (orientation contrast). Surface images with spherical clusters
   are growth features, not grains: use `--mode cluster` and report them
   separately. Do not compare the two.

## 2. Run

```bash
python scripts/run_grain.py --input <folder> --output <folder> \
    [--nm-per-px X | --bar-um X | --hfw-um X]
```

Useful overrides:

- `--recursive` — search sub-folders.
- `--no-info-bar` — keep the bottom information strip (only for already-cropped images).
- `--mode cluster` — count bright spherical clusters instead of segmenting grains.
- `--report-lang en|zh` — report and chart language (default `zh`).
- `--no-plots` — skip charts.
- `--skip-uncalibrated` — process the images that can be calibrated and list the rest in `failures.txt`.

Do not change segmentation parameters unless the overlay image proves the
defaults wrong. If you do, state which parameter changed and why.

## 3. After running

1. Read `<output>/05_csv/summary.csv` and `<output>/report.md`.
2. Report for every sample: grain count, **median** and mean equivalent
   diameter, analysed-area fraction, calibration source, and every warning.
3. Tell the user to open `<output>/03_overlay/` and check that the red
   boundaries follow grey-level steps. This is a required verification step;
   the numbers are not trustworthy without it.
4. Keep these caveats in the answer:
   - the resolvable limit is about 3–4 px; smaller structures are rejected, so
     the median is a conservative (high) estimate;
   - weak-contrast images have lower absolute reliability — do not compare
     their absolute values across samples without saying so;
   - the method is semi-automatic, not a ground truth.

## 4. Interpreting warnings

| Warning | Meaning | Action |
|---|---|---|
| `unresolvable slivers = N%` | Much of the field is below the resolution limit | Report as an upper-bound measurement; suggest higher magnification |
| `only N% of the field was analysed` | Most of the image was rejected | Treat the result as qualitative |
| `noise sigma = X` | Contrast is close to the noise level | Flag the sample as low-confidence |
| `only N grains measured` | Small sample | Do not draw conclusions from the distribution shape |
| `all grains touch the border` | Interior-only statistics unavailable | Report full-field numbers with the caveat |

## 5. Output layout

```
01_enhanced/    denoised + contrast-enhanced image
02_plateaus/    mean-shift plateau image (grain boundaries are clearest here)
03_overlay/     enhanced image + red boundaries  <- inspect these
04_colored/     each grain randomly coloured
05_csv/         <sample>_grains.csv, summary.csv, _diameters.json
06_charts/      histogram, distribution lines, cumulative curve, mean vs median
report.md       calibration table, results, warnings, caveats
```

## 6. Failure modes

- `cannot calibrate` — no tag 34118 and no explicit calibration. Ask the user;
  do not invent a value.
- `segmentation produced no grains` — likely a surface/topography image or a
  blank image. Switch to `--mode cluster` or check the input.
- A sample with a very different nm/px from the others is expected for ZEISS
  exports; calibration is per image on purpose.
