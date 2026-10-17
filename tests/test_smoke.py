# -*- coding: utf-8 -*-
"""End-to-end smoke test on synthetic images (no real data required)."""
from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


import make_demo  # noqa: E402
import run_grain  # noqa: E402


def _read_summary(path):
    with open(path, encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def run_grain_smoke(base):
    source = base / "input"
    source.mkdir(parents=True, exist_ok=True)
    make_demo.make_grain_image(source / "demo.tif", n_seeds=160, seed=11)

    output = base / "output"
    code = run_grain.main([
        "--input", str(source),
        "--output", str(output),
        "--nm-per-px", "8.0",
        "--min-size", "40",
        "--min-grains", "10",
    ])
    assert code == 0, f"run_grain returned {code}"

    rows = _read_summary(output / "05_csv" / "summary.csv")
    assert len(rows) == 1
    row = rows[0]
    assert int(row["n"]) > 0
    assert int(row["n_interior"]) > 0
    assert float(row["median_int_nm"]) > 0

    diameters = json.loads(
        (output / "05_csv" / "_diameters.json").read_text(encoding="utf-8"))
    assert len(diameters["demo"]["interior"]) > 0

    assert (output / "03_overlay" / "demo_overlay.png").exists()
    assert (output / "04_colored" / "demo_colored.png").exists()
    assert (output / "report.md").exists()
    assert (output / "06_charts" / "size_distribution_hist.png").exists()
    return row


def run_cluster_smoke(base):
    source = base / "surface"
    source.mkdir(parents=True, exist_ok=True)
    make_demo.make_cluster_image(source / "clusters.tif", n_clusters=120, seed=13)

    output = base / "cluster_output"
    code = run_grain.main([
        "--input", str(source),
        "--output", str(output),
        "--nm-per-px", "8.0",
        "--mode", "cluster",
    ])
    assert code == 0, f"run_grain returned {code}"

    rows = _read_summary(output / "05_csv" / "summary.csv")
    assert len(rows) == 1
    assert int(rows[0]["n_clusters"]) > 0
    assert (output / "03_overlay" / "clusters_cluster_marks.png").exists()


def test_end_to_end(tmp_path):
    run_grain_smoke(Path(tmp_path))


def test_cluster_mode(tmp_path):
    run_cluster_smoke(Path(tmp_path))


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        row = run_grain_smoke(base / "grains")
        print("grain smoke ok:", row["sample"], row["n_interior"], "grains")
        run_cluster_smoke(base / "clusters")
        print("cluster smoke ok")
