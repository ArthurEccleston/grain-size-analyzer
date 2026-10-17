# -*- coding: utf-8 -*-
"""Distribution charts for grain-size results.

Reads ``05_csv/_diameters.json`` produced by ``run_grain.py`` and writes four
figures to ``06_charts``.  Only grains that do not touch the image border are
plotted, matching the headline statistics.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASE = "#c3c2b7"

PALETTE = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100",
           "#8a5cf6", "#d6457a", "#4aa3b8", "#7a7a52")

LABELS = {
    "zh": {
        "x": "等效圆直径 (nm)",
        "freq": "频率 (%)",
        "cum": "累积频率 (%)",
        "median": "中位",
        "title_hist": "晶粒粒径分布（等效圆直径，仅统计不接触图像边缘的晶粒）",
        "title_lines": "样品粒径分布对比",
        "title_cum": "累积粒径分布（圆点为中位径）",
        "title_bar": "平均粒径与中位粒径对比（实心=中位，浅色=平均）",
        "mean": "平均",
        "median_short": "中位",
    },
    "en": {
        "x": "Equivalent circle diameter (nm)",
        "freq": "Frequency (%)",
        "cum": "Cumulative frequency (%)",
        "median": "median",
        "title_hist": "Grain-size distribution (equivalent circle diameter, interior grains only)",
        "title_lines": "Grain-size distributions",
        "title_cum": "Cumulative grain-size distribution (dots = median)",
        "title_bar": "Mean vs median grain size (solid = median, pale = mean)",
        "mean": "mean",
        "median_short": "median",
    },
}


def _style(ax, text_color=INK2):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(BASE)
    ax.tick_params(colors=MUTED, labelsize=11, length=3)
    ax.grid(True, color=GRID, lw=0.7, alpha=1.0)
    ax.set_axisbelow(True)


def _set_fonts(lang):
    chinese = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC",
               "Source Han Sans SC", "WenQuanYi Zen Hei"]
    fallback = ["Arial", "DejaVu Sans"]
    plt.rcParams["font.sans-serif"] = (chinese if lang == "zh" else []) + fallback
    plt.rcParams["axes.unicode_minus"] = False


def _bins(diameters):
    upper = float(np.percentile(diameters, 99.5))
    if not np.isfinite(upper):
        upper = 1500.0
    upper = max(300.0, min(upper, 3000.0))
    step = 75.0 if upper <= 1500.0 else 150.0
    return np.arange(0, upper + step, step)


def make_charts(results_dir, lang="zh"):
    results_dir = Path(results_dir)
    data_path = results_dir / "05_csv" / "_diameters.json"
    if not data_path.exists():
        raise FileNotFoundError(f"missing {data_path}")

    data = json.loads(data_path.read_text(encoding="utf-8"))
    samples = [name for name, item in data.items() if item.get("interior")]
    if not samples:
        raise ValueError("no interior grain diameters to plot")

    text = LABELS.get(lang, LABELS["en"])
    _set_fonts(lang)
    colors = {name: PALETTE[i % len(PALETTE)] for i, name in enumerate(samples)}
    interior = {name: np.asarray(data[name]["interior"], dtype=float) for name in samples}
    all_values = np.concatenate([interior[name] for name in samples])
    bins = _bins(all_values)
    centres = (bins[:-1] + bins[1:]) / 2.0

    out = results_dir / "06_charts"
    out.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------- histograms
    ncols = 2 if len(samples) > 1 else 1
    nrows = int(np.ceil(len(samples) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(5.6 * ncols, 3.9 * nrows),
                             sharex=True, sharey=True, squeeze=False)
    fig.patch.set_facecolor(SURFACE)
    for ax, name in zip(axes.ravel(), samples):
        values = interior[name]
        weights = np.ones_like(values) / max(len(values), 1) * 100.0
        ax.hist(values, bins=bins, weights=weights,
                color=colors[name], edgecolor=SURFACE, linewidth=1.2)
        median = float(np.median(values))
        ax.axvline(median, color=INK, lw=1.6, ls=(0, (4, 3)))
        ax.annotate(f"{text['median']} {median:.0f} nm",
                    xy=(median, ax.get_ylim()[1] * 0.92), xytext=(6, 0),
                    textcoords="offset points", color=INK, fontsize=11, va="top")
        ax.set_title(f"{name}    n = {len(values)}", color=INK, fontsize=13,
                     pad=8, loc="left")
        _style(ax)
    for ax in axes.ravel()[len(samples):]:
        ax.set_visible(False)
    for ax in axes[-1]:
        ax.set_xlabel(text["x"], color=INK2, fontsize=12)
    for ax in axes[:, 0]:
        ax.set_ylabel(text["freq"], color=INK2, fontsize=12)
    axes[0, 0].xaxis.set_major_locator(MultipleLocator(300))
    fig.suptitle(text["title_hist"], color=INK, fontsize=14, y=0.985)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out / "size_distribution_hist.png", dpi=170, facecolor=SURFACE)
    plt.close(fig)

    # ---------------------------------------------------------- line chart
    fig, ax = plt.subplots(figsize=(9.5, 6.0))
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    for name in samples:
        counts, _ = np.histogram(interior[name], bins=bins)
        total = max(int(counts.sum()), 1)
        ax.plot(centres, counts / total * 100.0, color=colors[name],
                lw=2.0, solid_capstyle="round", label=name)
        nonzero = np.where(counts > 0)[0]
        i = int(nonzero[-1]) if len(nonzero) else len(centres) - 1
        ax.annotate(name, xy=(centres[i], counts[i] / total * 100.0),
                    xytext=(-4, 4), textcoords="offset points",
                    color=INK2, fontsize=11, ha="right")
    ax.set_xlabel(text["x"], color=INK2, fontsize=12)
    ax.set_ylabel(text["freq"], color=INK2, fontsize=12)
    ax.set_title(text["title_lines"], color=INK, fontsize=14, loc="left", pad=10)
    ax.legend(samples, frameon=False, fontsize=11, labelcolor=INK2,
              ncols=min(len(samples), 4), loc="upper right")
    fig.tight_layout()
    fig.savefig(out / "size_distribution_lines.png", dpi=170, facecolor=SURFACE)
    plt.close(fig)

    # ---------------------------------------------------------- cumulative
    fig, ax = plt.subplots(figsize=(9.5, 6.0))
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    for name in samples:
        values = np.sort(interior[name])
        y = np.arange(1, len(values) + 1) / len(values) * 100.0
        ax.plot(values, y, color=colors[name], lw=2.0,
                solid_capstyle="round", label=name)
        index = int(np.searchsorted(y, 50))
        index = min(index, len(values) - 1)
        ax.plot([values[index]], [50], marker="o", ms=6, color=colors[name],
                mec=SURFACE, mew=1.6, zorder=5)
    ax.axhline(50, color=BASE, lw=1.0, ls=(0, (3, 3)))
    ax.set_xlim(0, float(np.percentile(all_values, 99.5)) * 1.05)
    ax.set_ylim(0, 100)
    ax.set_xlabel(text["x"], color=INK2, fontsize=12)
    ax.set_ylabel(text["cum"], color=INK2, fontsize=12)
    ax.set_title(text["title_cum"], color=INK, fontsize=14, loc="left", pad=10)
    ax.legend(samples, frameon=False, fontsize=11, labelcolor=INK2,
              ncols=min(len(samples), 4), loc="lower right")
    fig.tight_layout()
    fig.savefig(out / "size_cumulative.png", dpi=170, facecolor=SURFACE)
    plt.close(fig)

    # ---------------------------------------------------------- mean/median
    fig, ax = plt.subplots(figsize=(8.6, 5.6))
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    positions = np.arange(len(samples))
    width = 0.36
    for i, name in enumerate(samples):
        values = interior[name]
        mean, median = float(values.mean()), float(np.median(values))
        ax.bar(i - width / 2 + 0.02, mean, width - 0.04, color=colors[name],
               alpha=0.45, edgecolor=SURFACE, linewidth=1.2,
               label=text["mean"] if i == 0 else None)
        ax.bar(i + width / 2 - 0.02, median, width - 0.04, color=colors[name],
               edgecolor=SURFACE, linewidth=1.2,
               label=text["median_short"] if i == 0 else None)
        ax.annotate(f"{mean:.0f}", (i - width / 2 + 0.02, mean),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", color=INK2, fontsize=10)
        ax.annotate(f"{median:.0f}", (i + width / 2 - 0.02, median),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", color=INK2, fontsize=10)
    ax.set_xticks(positions)
    ax.set_xticklabels(samples, color=INK2, fontsize=12)
    ax.set_ylabel(text["x"], color=INK2, fontsize=12)
    ax.set_title(text["title_bar"], color=INK, fontsize=13, loc="left", pad=10)
    ax.legend(frameon=False, fontsize=11, labelcolor=INK2, loc="upper right")
    fig.tight_layout()
    fig.savefig(out / "mean_vs_median.png", dpi=170, facecolor=SURFACE)
    plt.close(fig)

    print(f"charts written to {out}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Draw grain-size charts.")
    parser.add_argument("results", help="output directory from run_grain.py")
    parser.add_argument("--lang", choices=("zh", "en"), default="zh")
    args = parser.parse_args()
    make_charts(args.results, args.lang)
