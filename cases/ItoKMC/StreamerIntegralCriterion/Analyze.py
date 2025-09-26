#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Extract fields from a block-wise ASCII simulation log; optionally smooth columns 3–6
with Savitzky–Golay; compute derivatives (columns 7–8) from Q columns; optionally
low-pass filter the derivatives; write an aligned .dat with a commented "Column" header.

Fields extracted per block:
  1. Time
  2. dt
  3. DeltaE(max)
  4. DeltaE(rel)
  5. Q (electrode)
  6. Q(ohmic)

Derived:
  7. d/dt Q (electrode)
  8. d/dt Q(ohmic)

Features:
  * Optional Savitzky–Golay smoothing on columns 3–6 (before differentiation).
  * Derivatives computed by finite differences using Time (fallback to dt).
  * Optional low-pass (bidirectional exponential) filter on derivative columns 7–8.
  * Fixed-width, consistently aligned columns; scientific notation with 8 decimals.
  * Units in the input (%, (C), etc.) are ignored.

Usage examples:
  # Basic extraction (no smoothing, no low-pass):
  python extract_timestep_data_filters.py -i pout.0 -o pout.out

  # With Savitzky–Golay smoothing (columns 3–6):
  python extract_timestep_data_filters.py -i pout.0 -o pout.out --sg --sg-window 9 --sg-order 3

  # With low-pass on derivatives (columns 7–8), tau=5e-12 seconds:
  python extract_timestep_data_filters.py -i pout.0 -o pout.out --lp --lp-tau 5e-12

  # Both smoothing and low-pass:
  python extract_timestep_data_filters.py -i pout.0 -o pout.out --sg --sg-window 11 --sg-order 3 --lp --lp-tau 1e-11
"""

import argparse
import math
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

# ---- Optional SciPy import (only needed if --sg is used) ----
def _import_savgol():
    try:
        from scipy.signal import savgol_filter
        return savgol_filter
    except Exception as e:
        print("Error: Savitzky–Golay smoothing requested (--sg) but SciPy is not available.", file=sys.stderr)
        print("Install SciPy or run without --sg, or let me add a NumPy-only alternative.", file=sys.stderr)
        sys.exit(1)

# --------- Regex patterns ----------
NUM = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?'

PATTERNS = {
    "Time": re.compile(rf'^\s*Time\s*=\s*(?P<val>{NUM})'),
    "dt": re.compile(rf'^\s*dt\s*=\s*(?P<val>{NUM})'),
    "DeltaE(max)": re.compile(rf'^\s*Delta\s*E\(max\)\s*=\s*(?P<val>{NUM})'),
    "DeltaE(rel)": re.compile(rf'^\s*Delta\s*E\(rel\)\s*=\s*(?P<val>{NUM})'),
    "Q (electrode)": re.compile(rf'^\s*Q\s*\(electrode\)\s*=\s*(?P<val>{NUM})'),
    "Q(ohmic)": re.compile(rf'^\s*Q\s*\(ohmic\)\s*=\s*(?P<val>{NUM})'),
}

FIELDS = [
    "Time",
    "dt",
    "DeltaE(max)",
    "DeltaE(rel)",
    "Q (electrode)",
    "Q(ohmic)",
    "d/dt Q (electrode)",
    "d/dt Q(ohmic)",
]

BLOCK_START = re.compile(r'^\s*Driver::Time step report\b')

COMMENT_HEADER = [
    "# Data is organized as follows:",
    "# Column 1: Time",
    "# Column 2: Time step (dt)",
    "# Column 3: Delta E(max) %          (Savitzky–Golay smoothed if --sg)",
    "# Column 4: Delta E(rel) %          (Savitzky–Golay smoothed if --sg)",
    "# Column 5: Q (electrode)           (Savitzky–Golay smoothed if --sg)",
    "# Column 6: Q (ohmic)               (Savitzky–Golay smoothed if --sg)",
    "# Column 7: d/dt Q (electrode)      (from Column 5; low-pass if --lp)",
    "# Column 8: d/dt Q (ohmic)          (from Column 6; low-pass if --lp)",
]

# ---------- Parsing ----------
def parse_file(in_path: str) -> List[Dict[str, float]]:
    rows: List[Dict[str, float]] = []
    current: Dict[str, float] = {}

    def flush_current():
        nonlocal current
        if current:
            rows.append(current)
            current = {}

    with open(in_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if BLOCK_START.search(line):
                flush_current()
                continue
            if PATTERNS["Time"].search(line) and "Time" in current:
                flush_current()
            for key, pat in PATTERNS.items():
                m = pat.search(line)
                if m:
                    try:
                        current[key] = float(m.group("val"))
                    except ValueError:
                        pass
                    break

    flush_current()
    return rows

# ---------- Utility: Savitzky–Golay smoothing with NaN handling ----------
def _odd_leq(n: int) -> int:
    return n if n % 2 == 1 else max(1, n - 1)

def _choose_window(n: int, req_window: int, polyorder: int) -> Optional[int]:
    if n <= polyorder:
        return None
    W = min(req_window, n)
    W = _odd_leq(W)
    if W <= polyorder:
        W = polyorder + 1 if (polyorder + 1) % 2 == 1 else polyorder + 2
        if W > n:
            return None
    return W

def savgol_smooth_with_nans(x: List[Optional[float]],
                            window_length: int,
                            polyorder: int) -> List[Optional[float]]:
    arr = np.asarray(x, dtype=float)
    n = arr.size
    if n == 0:
        return x
    valid = np.isfinite(arr)
    n_valid = int(valid.sum())
    if n_valid <= polyorder:
        return [float('nan') if not np.isfinite(v) else v for v in arr]

    W = _choose_window(n, window_length, polyorder)
    if W is None or W < 3:
        return [float('nan') if not np.isfinite(v) else v for v in arr]

    idx = np.arange(n)
    if n_valid < n:
        arr_filled = np.interp(idx, idx[valid], arr[valid])
    else:
        arr_filled = arr

    savgol_filter = _import_savgol()
    try:
        smoothed = savgol_filter(arr_filled, window_length=W, polyorder=polyorder, mode="interp")
    except Exception:
        smoothed = arr_filled

    smoothed[~valid] = np.nan
    return smoothed.tolist()

# ---------- Derivative (finite differences) ----------
def _safe_sub(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return a - b

def _safe_div(num: Optional[float], denom: Optional[float]) -> Optional[float]:
    if num is None or denom is None:
        return None
    if not (math.isfinite(num) and math.isfinite(denom) and denom != 0.0):
        return None
    return num / denom

def compute_derivative(values: List[Optional[float]],
                       times: List[Optional[float]],
                       dts: List[Optional[float]]) -> List[float]:
    n = len(values)
    out = [float('nan')] * n
    if n == 0:
        return out

    def delta_t(i: int, j: int, prefer_dt_index: Optional[int] = None) -> Optional[float]:
        if not (0 <= i < n and 0 <= j < n):
            return None
        ti, tj = times[i], times[j]
        if ti is not None and tj is not None:
            dt_val = ti - tj
            if math.isfinite(dt_val) and dt_val != 0.0:
                return dt_val
        if prefer_dt_index is not None:
            dt_alt = dts[prefer_dt_index]
            if dt_alt is not None and math.isfinite(dt_alt) and dt_alt > 0.0:
                return dt_alt
        return None

    for i in range(n):
        vi = values[i]
        if vi is None or not math.isfinite(vi):
            out[i] = float('nan')
            continue

        d = None
        if n == 1:
            d = None
        elif i == 0:
            num = _safe_sub(values[1], values[0])
            denom = delta_t(1, 0, prefer_dt_index=0)
            d = _safe_div(num, denom)
        elif i == n - 1:
            num = _safe_sub(values[n - 1], values[n - 2])
            denom = delta_t(n - 1, n - 2, prefer_dt_index=n - 1)
            d = _safe_div(num, denom)
        else:
            num = _safe_sub(values[i + 1], values[i - 1])
            denom = delta_t(i + 1, i - 1)
            d = _safe_div(num, denom)
            if d is None:
                num = _safe_sub(values[i], values[i - 1])
                denom = delta_t(i, i - 1, prefer_dt_index=i)
                d = _safe_div(num, denom)

        out[i] = d if d is not None else float('nan')
    return out

# ---------- Low-pass filter: bidirectional exponential (handles nonuniform Δt) ----------
def _segments_finite(x: np.ndarray, t: np.ndarray) -> List[Tuple[int, int]]:
    """Return (start, end) inclusive indices of contiguous segments where both x and t are finite."""
    finite = np.isfinite(x) & np.isfinite(t)
    if not finite.any():
        return []
    segs = []
    n = len(x)
    i = 0
    while i < n:
        if not finite[i]:
            i += 1
            continue
        s = i
        while i + 1 < n and finite[i + 1]:
            i += 1
        e = i
        segs.append((s, e))
        i += 1
    return segs

def lowpass_ema_bidirectional(values: List[Optional[float]],
                              times: List[Optional[float]],
                              tau: float) -> List[float]:
    """
    Zero-phase (forward+backward) exponential moving average on nonuniform samples.
    - alpha_i = 1 - exp(-Δt_i/tau) per step (uses actual time deltas).
    - Processes each contiguous finite segment independently (does not interpolate across NaNs).
    - For degenerate or nonpositive Δt, it resets (alpha=1) to avoid smearing across time reversals.

    Returns list with NaN where input was non-finite.
    """
    if tau is None or not math.isfinite(tau) or tau <= 0.0:
        # No filtering
        return [float(v) if (isinstance(v, (int, float)) and math.isfinite(v)) else float('nan') for v in values]

    x = np.asarray(values, dtype=float)
    t = np.asarray(times, dtype=float)
    n = x.size
    y = np.full(n, np.nan, dtype=float)

    segs = _segments_finite(x, t)
    for s, e in segs:
        xs = x[s:e+1].copy()
        ts = t[s:e+1].copy()
        m = e - s + 1
        if m == 1:
            y[s] = xs[0]
            continue

        # Forward pass
        fwd = np.empty_like(xs)
        fwd[0] = xs[0]
        for i in range(1, m):
            dt = ts[i] - ts[i - 1]
            if not math.isfinite(dt) or dt <= 0.0:
                alpha = 1.0  # reset
            else:
                alpha = 1.0 - math.exp(-dt / tau)
            fwd[i] = (1.0 - alpha) * fwd[i - 1] + alpha * xs[i]

        # Backward pass
        bwd = np.empty_like(xs)
        bwd[-1] = xs[-1]
        for i in range(m - 2, -1, -1):
            dt = ts[i + 1] - ts[i]
            if not math.isfinite(dt) or dt <= 0.0:
                alpha = 1.0
            else:
                alpha = 1.0 - math.exp(-dt / tau)
            bwd[i] = (1.0 - alpha) * bwd[i + 1] + alpha * xs[i]

        ys = 0.5 * (fwd + bwd)
        y[s:e+1] = ys

    return y.tolist()

# ---------- Writer (aligned, scientific) ----------
def write_dat_aligned_with_comments(out_path: str,
                                    rows: List[Dict[str, float]],
                                    use_sg: bool,
                                    sg_window: int,
                                    sg_order: int,
                                    use_lp: bool,
                                    lp_tau: Optional[float],
                                    col_gap: int = 2):
    # Collect raw arrays
    T  = [rec.get("Time") for rec in rows]
    dT = [rec.get("dt") for rec in rows]
    Emax = [rec.get("DeltaE(max)") for rec in rows]
    Erel = [rec.get("DeltaE(rel)") for rec in rows]
    Qe   = [rec.get("Q (electrode)") for rec in rows]
    Qo   = [rec.get("Q(ohmic)") for rec in rows]

    # Optional Savitzky–Golay smoothing on columns 3–6
    if use_sg:
        Emax_s = savgol_smooth_with_nans(Emax, sg_window, sg_order)
        Erel_s = savgol_smooth_with_nans(Erel, sg_window, sg_order)
        Qe_s   = savgol_smooth_with_nans(Qe,   sg_window, sg_order)
        Qo_s   = savgol_smooth_with_nans(Qo,   sg_window, sg_order)
    else:
        Emax_s, Erel_s, Qe_s, Qo_s = Emax, Erel, Qe, Qo

    # Derivatives from (possibly smoothed) Q values
    dQe_dt = compute_derivative(Qe_s, T, dT)
    dQo_dt = compute_derivative(Qo_s, T, dT)

    # Optional low-pass filter on derivative columns
    if use_lp:
        dQe_dt = lowpass_ema_bidirectional(dQe_dt, T, lp_tau)
        dQo_dt = lowpass_ema_bidirectional(dQo_dt, T, lp_tau)

    # Compose output rows
    rows_data: List[List[Optional[float]]] = []
    for i, rec in enumerate(rows):
        rows_data.append([
            rec.get("Time"),
            rec.get("dt"),
            Emax_s[i],
            Erel_s[i],
            Qe_s[i],
            Qo_s[i],
            dQe_dt[i],
            dQo_dt[i],
        ])

    # Format strings with scientific notation and compute widths
    formatted_rows: List[List[str]] = []
    for vals in rows_data:
        svals = []
        for v in vals:
            if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
                svals.append("nan")
            else:
                svals.append(f"{v:.8e}")
        formatted_rows.append(svals)

    widths = []
    for j in range(len(FIELDS)):
        max_len = max((len(r[j]) for r in formatted_rows), default=3)
        widths.append(max_len)

    sep = " " * col_gap
    with open(out_path, "w", encoding="utf-8") as g:
        # Comment header
        for line in COMMENT_HEADER:
            g.write(line + "\n")
        g.write("\n")
        # Data rows
        for r in formatted_rows:
            g.write(sep.join(f"{val:>{w}}" for val, w in zip(r, widths)) + "\n")

# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser(
        description="Extract, (optionally) smooth, differentiate, and (optionally) low-pass filter; write aligned .dat with commented header."
    )
    ap.add_argument("-i", "--input", required=True, help="Path to the input ASCII log file", default="pout.0")
    ap.add_argument("-o", "--output", help="Path to the output .dat file", default="pout.out")

    # Savitzky–Golay options (columns 3–6)
    ap.add_argument("--sg", action="store_true", help="Apply Savitzky–Golay smoothing to columns 3–6 before derivatives")
    ap.add_argument("--sg-window", type=int, default=9, help="Savitzky–Golay window length (odd; reduced if needed)")
    ap.add_argument("--sg-order", type=int, default=3, help="Savitzky–Golay polynomial order (< window)")

    # Low-pass on derivatives (columns 7–8)
    ap.add_argument("--lp", action="store_true", help="Apply low-pass filter to derivative columns 7–8")
    ap.add_argument("--lp-tau", type=float, default=None, help="Low-pass time constant τ (seconds) for bidirectional EMA")

    args = ap.parse_args()

    in_path = args.input
    if not os.path.isfile(in_path):
        print(f"Error: input file not found: {in_path}", file=sys.stderr)
        sys.exit(1)

    out_path = args.output
    if not out_path:
        base, _ = os.path.splitext(in_path)
        out_path = base + ".dat"

    rows = parse_file(in_path)
    if not rows:
        print("Warning: no records found. Check that the input contains the expected fields.", file=sys.stderr)

    # Validate options
    if args.lp and (args.lp_tau is None or not math.isfinite(args.lp_tau) or args.lp_tau <= 0.0):
        print("Error: --lp requires a positive --lp-tau (seconds).", file=sys.stderr)
        sys.exit(1)
    if args.sg and args.sg_order >= args.sg_window:
        print("Error: --sg-order must be < --sg-window.", file=sys.stderr)
        sys.exit(1)

    write_dat_aligned_with_comments(
        out_path=out_path,
        rows=rows,
        use_sg=args.sg,
        sg_window=args.sg_window,
        sg_order=args.sg_order,
        use_lp=args.lp,
        lp_tau=args.lp_tau,
    )
    print(f"Wrote {len(rows)} rows to: {out_path}")

if __name__ == "__main__":
    main()
