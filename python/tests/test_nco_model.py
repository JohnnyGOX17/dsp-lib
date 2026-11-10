import numpy as np
from dsplib.lfsr import lfsr
from dsplib.nco import nco
from dsplib.spectral import sfdr_db


def test_lfsr16_maximal_length():
    s = lfsr(2**16, width=16)
    assert len(set(s[:-1].tolist())) == 2**16 - 1 and s[-1] == s[0]


def test_nco_matches_ideal_over_all_phases():
    # One ROM step per sample visits every truncated phase once, across all four quadrants.
    phase_w, addr_w, out_w = 16, 6, 12
    p = addr_w + 2
    cos, sin = nco(
        1 << (phase_w - p), 1 << p, phase_w=phase_w, addr_w=addr_w, out_w=out_w
    )
    theta = (
        2 * np.pi * (np.arange(1 << p) + 0.5) / (1 << p)
    )  # half-LSB offset, as in the ROM
    amp = (1 << (out_w - 1)) - 1
    assert np.abs(cos - amp * np.cos(theta)).max() <= 0.5 + 1e-9
    assert np.abs(sin - amp * np.sin(theta)).max() <= 0.5 + 1e-9


def test_sfdr_of_known_spur():
    n = np.arange(8192)
    x = np.exp(2j * np.pi * 0.1 * n) + 10 ** (-80 / 20) * np.exp(2j * np.pi * 0.3 * n)
    assert abs(sfdr_db(x) - 80) < 0.5
