"""Validates the Kaggle notebooks locally by executing their code cells in
a simulated Kaggle filesystem (/kaggle/input + /kaggle/working).

Uses the bittensor venv python (torch-CPU + ViennaRNA wheel present) so every
kernel path is exercised exactly as on Kaggle, minus CUDA devices (kernels
fall back to device 'cpu' — the same code path, different hardware tag).

Run:  .venv-bt/bin/python scripts/validate_notebooks.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NB_DIR = ROOT / "notebooks"

# ---- 1. simulate /kaggle/input with the package as a dataset zip -----------
KAGGLE = Path(tempfile.mkdtemp(prefix="kaggle-sim-"))
(KAGGLE / "input").mkdir(parents=True)
(KAGGLE / "working").mkdir(parents=True)

zip_path = KAGGLE / "input" / "ribosome-network.zip"
with zipfile.ZipFile(zip_path, "w") as z:
    for item in ["ribosome", "neurons", "simulation", "tests", "data",
                 "requirements.txt"]:
        p = ROOT / item
        if p.is_dir():
            for f in p.rglob("*"):
                if f.is_file() and "__pycache__" not in str(f):
                    z.write(f, f.relative_to(ROOT))
        else:
            z.write(p, item)
print(f"[sim] dataset zip: {zip_path} ({zip_path.stat().st_size/1e6:.1f} MB)")

os.environ["MPLBACKEND"] = "Agg"

def run_notebook(nb_path: Path) -> bool:
    print(f"\n===== {nb_path.name} =====")
    nb = json.loads(nb_path.read_text())
    g = {"__name__": "__main__"}
    ok = True
    for i, cell in enumerate(nb["cells"]):
        if cell["cell_type"] != "code":
            continue
        src = "".join(cell["source"])
        # notebooks hardcode /kaggle/... — rewrite to the simulated paths
        src = src.replace("/kaggle/", str(KAGGLE) + "/")
        t0 = time.perf_counter()
        try:
            os.chdir(KAGGLE / "working")  # notebooks assume this cwd per cell
            exec(compile(src, f"{nb_path.name}:cell{i}", "exec"), g)
            print(f"  cell {i:2d} OK  ({time.perf_counter()-t0:.1f}s)")
        except Exception as exc:
            ok = False
            print(f"  cell {i:2d} FAIL ({time.perf_counter()-t0:.1f}s): "
                  f"{type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc(limit=3)
            break
    return ok

results = {}
for nb in sorted(NB_DIR.glob("*.ipynb")):
    results[nb.name] = run_notebook(nb)

print("\n===== SUMMARY =====")
for name, ok in results.items():
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")
shutil.rmtree(KAGGLE, ignore_errors=True)
sys.exit(0 if all(results.values()) else 1)
