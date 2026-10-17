# Grain Size Analyzer

Grain-size statistics for SEM orientation-contrast images (ESD1 and similar).

The tool takes a folder of scanning-electron images, calibrates each image to
nanometres independently, segments grain boundaries, rejects structures that
are too thin to resolve, and exports per-grain measurements, boundary overlays
and distribution charts.

It is deliberately conservative: anything below the resolution limit is
reported as "unresolvable" and excluded, never merged into a neighbouring
grain. The median it reports is therefore a conservative (slightly high)
estimate, not a lower bound.

## Features

- **Per-image calibration** from the ZEISS private TIFF tag 34118, an
  automatically detected scale bar, the horizontal field width, or an explicit
  nm/px value.
- **Automatic crop** of the bottom information strip (height is detected, not
  hard-coded).
- **Watershed segmentation** on a mean-shift plateau image, with seeds from the
  union of h-maxima and h-minima so dark grains are not missed.
- **Unresolvable-region rejection**: slivers thinner than 3 px and connected
  patches larger than any plausible grain are set to zero.
- **Optional cluster mode** for bright spherical surface features.
- CSV, overlay/coloured images, four distribution charts and a Markdown report.

## Installation

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Python 3.10–3.13. OpenCV must be the headless build (no GUI libraries needed).

## Quick start

```bash
python scripts/run_grain.py --input ./images --output ./results
```

If the images carry tag 34118, no calibration argument is needed. Otherwise:

```bash
# scale bar of known length (detected automatically in the bottom strip)
python scripts/run_grain.py -i ./images --bar-um 1.0

# horizontal field width
python scripts/run_grain.py -i ./images --hfw-um 20.7

# one value for every image
python scripts/run_grain.py -i ./images --nm-per-px 8.26
```

On Windows, `run.bat` forwards its arguments to the script:

```bat
run.bat -i .\images -o .\results
```

On Linux / macOS use `sh run.sh -i ./images -o ./results`.

## Calibration order

1. `--nm-per-px` (explicit override)
2. TIFF tag 34118, first value = pixel size (metres, micrometres or nanometres;
   the unit is inferred from the magnitude)
3. `--bar-um` + automatic scale-bar detection
4. `--hfw-um`
5. otherwise the image is rejected — the tool never guesses

The source used for each image is written to `summary.csv` and `report.md`.

## Output

```
01_enhanced/    denoised + contrast-enhanced image
02_plateaus/    mean-shift plateau image
03_overlay/     enhanced image + red grain boundaries  <- inspect these
04_colored/     each grain randomly coloured
05_csv/         <sample>_grains.csv, summary.csv, _diameters.json
06_charts/      histogram, distribution lines, cumulative curve, mean vs median
report.md       calibration table, results, warnings
```

Per-grain columns: area, equivalent-circle diameter, major/minor axis, aspect
ratio, inscribed width, border flag, mean and standard deviation of grey level.

Headline statistics use **interior grains only** (grains not touching the image
border), because cropped grains are biased small.

## Quality checks

The report flags:

- slivers rejected as a fraction of the segmented area (> 15 %);
- analysed area below 50 % of the field;
- noise sigma above 6 grey levels;
- fewer than 30 measured grains.

These are warnings, not errors. A flagged result can still be useful, but it
must be reported with the caveat.

## Limitations

- Designed for **orientation contrast** (grains differ in brightness). Surface
  topography images will not segment correctly.
- Resolvable limit is about **3–4 px**; smaller structures are excluded. Raise
  the magnification rather than lowering the threshold.
- Bright spherical features on surface images are **growth clusters, not
  grains**. Use `--mode cluster` and never compare the two size scales.
- The segmentation is semi-automatic. Always inspect `03_overlay/`: red
  boundaries should follow grey-level steps. A boundary cutting through a
  visually uniform grain interior is an over-segmentation.
- Weak-contrast images (noise comparable to the grain-boundary step) have lower
  absolute reliability.

## Cluster mode

```bash
python scripts/run_grain.py -i ./surface_images --mode cluster --nm-per-px 76.9
```

Top-hat transform → Gaussian smoothing → local maxima. The output is a count
and an area-based equivalent spacing, plus a marked image for visual checking.
This mode does **not** measure grains.

## Demo

No experimental data is included. Generate synthetic images and run the
pipeline:

```bash
python scripts/make_demo.py
python scripts/run_grain.py -i examples/demo_input --nm-per-px 8.0
```

The synthetic grain image also contains a 1 µm scale bar, so
`--bar-um 1.0` can be used instead of `--nm-per-px`. The synthetic images are
for exercising the pipeline; they do not validate measurement accuracy.

## Tests

```bash
python tests/test_smoke.py
# or, if pytest is installed:
python -m pytest tests/ -q
```

The smoke test generates synthetic images, runs both modes end to end and
checks the CSV, JSON, overlay and chart outputs.

## Using as an agent skill

This repository is also a portable agent skill: `SKILL.md` describes when to
run the tool, how to calibrate, what to check after a run, and how to report
the caveats. Copy the whole folder into your agent's user-level skills
directory and it will be picked up automatically. The scripts are
self-contained and can be used from the command line without the skill layer.

## License

MIT — see [LICENSE](LICENSE).
