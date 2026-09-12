"""Refold oracle abstraction.

The chaperone's core tool: given a designed sequence, refold it and hand the
structure back for comparison against the target. Four implementations:

  StubOracle        pure-Python/numpy Nussinov (deterministic, memoized)
  ViennaRNAOracle   shells out to `RNAfold` when installed - physics-grade 2D
  PyViennaRNAOracle official ViennaRNA Python bindings (pip wheel)
  RhoFoldOracle     3D refolding via RhoFold+ (repo + checkpoint required):
                    PDB -> C3' contact map -> non-crossing dot-bracket

Selection: 'auto' picks the best oracle available at runtime (RhoFold+ if
configured > pyviennarna > RNAfold CLI > Nussinov). All oracles return a
dot-bracket string with () pairs only; pseudoknot targets ([]) therefore
cannot be fully matched, which the target pool encodes as difficulty tag.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

from .rna import dot_bracket_from_pairs, pair_score

MIN_LOOP = 3


class BaseOracle:
    name = "base"

    def fold(self, sequence: str) -> str:
        raise NotImplementedError

    def fold_batch(self, sequences: List[str]) -> List[str]:
        return [self.fold(s) for s in sequences]


# --------------------------------------------------------------------------
# Nussinov core (module-level, lru-cached by sequence)
# --------------------------------------------------------------------------
def _score_matrix(seq, np):
    n = len(seq)
    s = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            s[i, j] = pair_score(seq[i], seq[j])
    return s


def _nussinov_dp(seq: str, np):
    """dp[i, j] = max pairs (weighted) obtainable in seq[i..j]."""
    n = len(seq)
    s = _score_matrix(seq, np)
    dp = np.zeros((n, n))
    for span in range(1, n):
        i_range = range(0, n - span)
        # term1 = dp[i+1, j] ; term2 = dp[i, j-1] ; term3 = dp[i+1, j-1] + s
        t1 = dp[np.arange(1, n - span + 1), np.arange(span, n)]
        t2 = dp[np.arange(0, n - span), np.arange(span - 1, n - 1)]
        t3 = dp[np.arange(1, n - span + 1), np.arange(span - 1, n - 1)] + s[
            np.arange(0, n - span), np.arange(span, n)
        ]
        # only allow the pair when the hairpin loop is big enough
        # loop size = span - 1 >= MIN_LOOP  ->  span >= MIN_LOOP + 1
        pair_term = t3 if span >= MIN_LOOP + 1 else np.zeros(n - span)
        best = np.maximum(np.maximum(t1, t2), pair_term)
        # split term: max_k dp[i, k] + dp[k+1, j], k in [i+1, j-1]
        if span >= 2 * MIN_LOOP + 2:
            k_span = span - 1  # number of k candidates
            # dp[i, k]: diagonal offset d = k - i, d in [1, span-1]
            # dp[k+1, j]: diagonal offset span - d - 1, row k+1 = i + d + 1
            cand = np.full((k_span, n - span), -1.0)
            for d in range(1, span):
                left = dp[np.arange(0, n - span), np.arange(d, n - span + d)]
                right = dp[np.arange(d + 1, n - span + d + 1), np.arange(span, n)]
                cand[d - 1, : len(left)] = left + right[: n - span]
            best = np.maximum(best, cand.max(axis=0))
        dp[np.arange(0, n - span), np.arange(span, n)] = best
    return dp


def _nussinov_traceback(seq: str, dp, np) -> List[Tuple[int, int]]:
    n = len(seq)
    pairs: List[Tuple[int, int]] = []
    stack: List[Tuple[int, int]] = [(0, n - 1)] if n else []
    while stack:
        i, j = stack.pop()
        if i >= j or j - i < MIN_LOOP + 1:
            continue
        cur = dp[i, j]
        if abs(dp[i + 1, j] - cur) < 1e-9:
            stack.append((i + 1, j))
            continue
        if abs(dp[i, j - 1] - cur) < 1e-9:
            stack.append((i, j - 1))
            continue
        if (j - i - 1) >= MIN_LOOP and pair_score(seq[i], seq[j]) > 0:
            inside = dp[i + 1, j - 1] if j - 1 >= i + 1 else 0.0
            if abs(pair_score(seq[i], seq[j]) + inside - cur) < 1e-9:
                pairs.append((i, j))
                stack.append((i + 1, j - 1))
                continue
        split_found = False
        if j - i >= 2 * MIN_LOOP + 3:
            for k in range(i + 1, j):
                if abs(dp[i, k] + dp[k + 1, j] - cur) < 1e-9:
                    stack.append((i, k))
                    stack.append((k + 1, j))
                    split_found = True
                    break
        if not split_found:  # pragma: no cover - numeric safety
            stack.append((i + 1, j))
    return sorted(pairs)


@lru_cache(maxsize=200_000)
def nussinov_fold(sequence: str) -> str:
    import numpy as np

    seq = sequence.upper().replace("T", "U")
    if not seq:
        return ""
    dp = _nussinov_dp(seq, np)
    pairs = _nussinov_traceback(seq, dp, np)
    return dot_bracket_from_pairs(pairs, len(seq))


class StubOracle(BaseOracle):
    name = "stub-nussinov"

    def fold(self, sequence: str) -> str:
        return nussinov_fold(sequence)


class ViennaRNAOracle(BaseOracle):
    """Physics-grade 2D folding via the RNAfold executable."""

    name = "viennarna"

    def __init__(self, binary: str = "RNAfold") -> None:
        if shutil.which(binary) is None:
            raise FileNotFoundError(
                "RNAfold not found; install ViennaRNA or fall back to StubOracle"
            )
        self.binary = binary

    def fold(self, sequence: str) -> str:
        seq = sequence.upper().replace("T", "U")
        out = subprocess.run(
            [self.binary, "--noPS"],
            input=seq, capture_output=True, text=True, check=True,
        ).stdout
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        return lines[1].split()[0] if len(lines) >= 2 else "." * len(seq)


class PyViennaRNAOracle(BaseOracle):
    """Physics-grade 2D folding via the official ViennaRNA Python bindings.

    Works where the CLI binary is unavailable (pip install viennarna gives
    the wheel with libRNA bundled) - e.g. Kaggle images without conda.
    """

    name = "pyviennarna"

    def __init__(self) -> None:
        try:
            import ViennaRNA  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "pip install viennarna (or install the ViennaRNA system "
                "package and use ViennaRNAOracle)"
            ) from exc
        self._vr = ViennaRNA

    def fold(self, sequence: str) -> str:
        seq = sequence.upper().replace("T", "U")
        struct, _mfe = self._vr.RNA.fold(seq)
        # normalize pseudoknot-ish chars to () only
        return "".join(c if c in "()" else "." for c in struct)


class RhoFoldOracle(BaseOracle):
    """RhoFold+ 3D refolding adapter (production chaperone oracle).

    Given a designed sequence we:
      1. run RhoFold+ inference in a checkout of the official repo
         (env/subnet args: --rhofold-repo, --rhofold-ckpt)
      2. parse the predicted model PDB and extract C3' coordinates
      3. build a distance contact map (cutoff 8.0 A, the standard RNA
         C3'-C3' contact threshold)
      4. reduce to a non-crossing dot-bracket (greedy by distance,
         MIN_LOOP respected) so the composite score pipeline is unchanged

    NOTE: for publication-grade base-pair typing (Watson-Crick/Wobble
    classification) pipe the PDB through DSSR/X3DNA; this dependency-free
    reduction is intentionally simple and conservative.

    Raises NotImplementedError when no repo/checkpoint is configured so the
    factory and CI paths fall back to ViennaRNA/Nussinov cleanly.
    """

    name = "rhofold"
    CONTACT_CUTOFF_A = 8.0

    def __init__(self, repo: str = "", checkpoint: str = "") -> None:
        self.repo = repo or os.environ.get("RIBOSOME_RHOFOLD_REPO", "")
        self.checkpoint = checkpoint or os.environ.get("RIBOSOME_RHOFOLD_CKPT", "")
        if not self.repo or not self.checkpoint:
            raise NotImplementedError(
                "RhoFoldOracle requires the RhoFold+ repo and checkpoint "
                "(--rhofold-repo/--rhofold-ckpt or env RIBOSOME_RHOFOLD_REPO/"
                "RIBOSOME_RHOFOLD_CKPT). Fall back to ViennaRNA/Nussinov."
            )
        self.repo = Path(self.repo)
        self.checkpoint = Path(self.checkpoint)
        if not self.repo.exists():
            raise NotImplementedError(f"RhoFold+ repo not found: {self.repo}")
        if not self.checkpoint.exists():
            raise NotImplementedError(
                f"RhoFold+ checkpoint not found: {self.checkpoint}"
            )
        self._device = self._pick_device()

    @staticmethod
    def _pick_device() -> str:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    # ------------------------------------------------------- inference ----
    def _run_rhofold(self, sequence: str, workdir: Path) -> Path:
        import subprocess as sp
        import tempfile

        workdir.mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable, str(self.repo / "inference.py"),
            "--rna_seq", sequence.upper().replace("T", "U"),
            "--config", str(self.repo / "config.yaml"),
            "--ckpt", str(self.checkpoint),
            "--device", self._device,
            "--output_dir", str(workdir),
        ]
        sp.run(cmd, check=True, capture_output=True, text=True, timeout=1800)
        pdbs = sorted(workdir.glob("*.pdb"))
        if not pdbs:
            raise RuntimeError(f"RhoFold+ produced no PDB in {workdir}")
        return pdbs[0]

    # ------------------------------------------------------------ PDB ----
    @staticmethod
    def parse_c3_coords(pdb_path: Path) -> List[Tuple[float, float, float]]:
        """Per-residue C3' coordinates (fallback: first atom of residue)."""
        by_res: "OrderedDict[int, Tuple[float, float, float]]" = OrderedDict()
        first: "OrderedDict[int, Tuple[float, float, float]]" = OrderedDict()
        for line in pdb_path.read_text().splitlines():
            if not line.startswith(("ATOM", "HETATM")):
                continue
            try:
                resid = int(line[22:26])
                x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
            except ValueError:
                continue
            atom = line[12:16].strip()
            if atom == "C3'":
                by_res[resid] = (x, y, z)
            elif resid not in first:
                first[resid] = (x, y, z)
        coords = by_res or first
        return list(coords.values())

    def coords_to_dot_bracket(self, coords: List[Tuple[float, float, float]]) -> str:
        """Contact map -> non-crossing dot-bracket (greedy, MIN_LOOP)."""
        n = len(coords)
        if n < 2 * MIN_LOOP + 2:
            return "." * n
        pairs: List[Tuple[float, int, int]] = []
        for i in range(n):
            xi, yi, zi = coords[i]
            for j in range(i + MIN_LOOP + 1, n):
                xj, yj, zj = coords[j]
                d2 = (xi - xj) ** 2 + (yi - yj) ** 2 + (zi - zj) ** 2
                if d2 <= self.CONTACT_CUTOFF_A ** 2:
                    pairs.append((d2, i, j))
        pairs.sort()  # shortest contacts are the most confident
        accepted: List[Tuple[int, int]] = []

        def crosses(a: Tuple[int, int], b: Tuple[int, int]) -> bool:
            return a[0] < b[0] < a[1] < b[1] or b[0] < a[0] < b[1] < a[1]

        for _d2, i, j in pairs:
            if all(not crosses((i, j), p) for p in accepted):
                accepted.append((i, j))
        return dot_bracket_from_pairs(accepted, n)

    # --------------------------------------------------------- oracle ----
    def fold(self, sequence: str) -> str:
        import tempfile

        seq = sequence.upper().replace("T", "U")
        if not seq:
            return ""
        with tempfile.TemporaryDirectory(prefix="rhofold-") as tmp:
            pdb = self._run_rhofold(seq, Path(tmp))
            coords = self.parse_c3_coords(pdb)
        return self.coords_to_dot_bracket(coords)

    def fold_batch(self, sequences: List[str]) -> List[str]:
        """Batch refold; on multi-GPU hosts round-robins CUDA devices."""
        try:
            import torch

            n_gpu = torch.cuda.device_count()
        except ImportError:
            n_gpu = 0
        if n_gpu <= 1:
            return [self.fold(s) for s in sequences]
        import subprocess as sp
        import tempfile

        def one(seq: str, device: str) -> str:
            with tempfile.TemporaryDirectory(prefix="rhofold-") as tmp:
                old = self._device
                self._device = device
                try:
                    pdb = self._run_rhofold(
                        seq.upper().replace("T", "U"), Path(tmp)
                    )
                    coords = self.parse_c3_coords(pdb)
                finally:
                    self._device = old
            return self.coords_to_dot_bracket(coords)

        from concurrent.futures import ThreadPoolExecutor

        devices = [f"cuda:{k}" for k in range(n_gpu)]
        with ThreadPoolExecutor(max_workers=n_gpu) as pool:
            return list(
                pool.map(lambda args_: one(*args_), zip(sequences, _cycle(devices)))
            )


def _cycle(items):  # pragma: no cover - trivial helper
    while True:
        for it in items:
            yield it


def get_oracle(name: str = "auto") -> BaseOracle:
    """Factory: 'stub' | 'viennarna' | 'pyviennarna' | 'rhofold' | 'auto'.

    'auto' prefers the best oracle available at runtime:
    RhoFold+ (if env-configured) > pyviennarna > RNAfold CLI > Nussinov.
    """
    if name == "stub":
        return StubOracle()
    if name == "viennarna":
        return ViennaRNAOracle()
    if name == "pyviennarna":
        return PyViennaRNAOracle()
    if name == "rhofold":
        return RhoFoldOracle()
    if name == "auto":
        if os.environ.get("RIBOSOME_RHOFOLD_REPO") and os.environ.get(
            "RIBOSOME_RHOFOLD_CKPT"
        ):
            try:
                return RhoFoldOracle()
            except NotImplementedError:
                pass
        for candidate in (PyViennaRNAOracle, ViennaRNAOracle):
            try:
                return candidate()
            except (ImportError, FileNotFoundError):
                continue
        return StubOracle()
    raise ValueError(f"unknown oracle {name!r}")
