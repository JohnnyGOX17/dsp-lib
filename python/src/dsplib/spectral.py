"""Spectral analysis helpers shared by models, testbenches and plots."""

import numpy as np
from scipy.signal import windows

# Kaiser beta 16 gives ~150 dB sidelobes, enough to measure SFDR of 16+ bit signals.
KAISER_BETA = 16.0
# Main-lobe half-width (bins) to exclude around the carrier for that window.
MAIN_LOBE_BINS = 8


def spectrum_db(x: np.ndarray, fs: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Windowed power spectrum in dB relative to the peak. Two-sided (fftshifted) for
    complex input, one-sided for real input."""
    x = np.asarray(x)
    w = windows.kaiser(len(x), KAISER_BETA)
    if np.iscomplexobj(x):
        X = np.fft.fftshift(np.fft.fft(x * w))
        f = np.fft.fftshift(np.fft.fftfreq(len(x), 1 / fs))
    else:
        X = np.fft.rfft(x * w)
        f = np.fft.rfftfreq(len(x), 1 / fs)
    p = np.abs(X) ** 2
    return f, 10 * np.log10(np.maximum(p / p.max(), 1e-30))


def carrier_and_spur(p: np.ndarray, is_complex: bool = True) -> tuple[int, int]:
    """Bins of the carrier and of the largest spur outside the carrier's main lobe (and
    outside DC for one-sided spectra of real signals)."""
    k = int(np.argmax(p))
    q = p.copy()
    q[max(k - MAIN_LOBE_BINS, 0) : k + MAIN_LOBE_BINS + 1] = -np.inf
    if not is_complex:
        q[: MAIN_LOBE_BINS + 1] = -np.inf
    return k, int(np.argmax(q))


def sfdr_db(x: np.ndarray) -> float:
    """Spurious-free dynamic range (dBc): carrier power over the largest spur."""
    _, p = spectrum_db(x)
    k, s = carrier_and_spur(p, np.iscomplexobj(x))
    return float(p[k] - p[s])
