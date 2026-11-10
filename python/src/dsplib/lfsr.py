"""Galois LFSR, bit-exact with hdl/common/lfsr.sv."""

import numpy as np

# Galois (right-shift) feedback masks for maximal-length LFSRs; bit (t-1) set for each tap t.
# Taps from Xilinx XAPP052.
MAX_LEN_POLY = {
    16: 0xB400,  # 16,14,13,11
    32: 0x80200003,  # 32,22,2,1
}


def lfsr(n: int, width: int = 32, poly: int | None = None, seed: int = 1) -> np.ndarray:
    """First `n` states, starting at `seed`, one shift per state."""
    poly = MAX_LEN_POLY[width] if poly is None else poly
    out = np.empty(n, dtype=np.uint64)
    state = seed
    for i in range(n):
        out[i] = state
        state = (state >> 1) ^ (poly if state & 1 else 0)
    return out
