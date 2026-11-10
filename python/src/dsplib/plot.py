"""Capture signals from testbenches and plot them (time + frequency domain).

Testbenches call `save_capture()` (before asserting, so failures still leave something to
look at); captures land in build/<block>/<config>/*.npz. They are
plotted after the sim when PLOT=1 (never in CI), or replayed later without re-simulating:

    python -m dsplib.plot build/nco            # or: just plot nco

Figures use a clean, print-ready style; the toolbar's save button defaults to vector PDF.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np

from dsplib.spectral import carrier_and_spur, spectrum_db

TIME_SAMPLES = 256  # samples shown in the time-domain view

# Categorical series colors, used in this order (colorblind-safe as adjacent pairs).
COLORS = [
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#6250d6",
    "#e34948",
]
INK = "#0b0b0b"  # titles
INK_2 = "#52514e"  # labels, annotations
MUTED = "#898781"  # tick labels
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

# Applied only inside show(), so importing dsplib never changes global rcParams.
STYLE = {
    "figure.figsize": (8, 5.5),
    "figure.facecolor": "white",
    "figure.constrained_layout.use": True,
    "figure.constrained_layout.h_pad": 0.12,
    "font.family": "sans-serif",
    "font.sans-serif": ["Inter", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "text.color": INK,
    "axes.facecolor": "white",
    "axes.edgecolor": AXIS,
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.labelcolor": INK_2,
    "axes.labelsize": 9.5,
    "axes.labelpad": 6,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.titlepad": 10,
    "axes.xmargin": 0,  # data runs edge to edge
    "axes.ymargin": 0,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "lines.linewidth": 0.8,
    "xtick.color": AXIS,
    "ytick.color": AXIS,
    "xtick.labelcolor": MUTED,
    "ytick.labelcolor": MUTED,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "xtick.major.size": 3,
    "ytick.major.size": 0,  # horizontal gridlines already mark y
    "xtick.major.width": 0.8,
    "legend.fontsize": 8.5,
    "legend.frameon": False,
    "legend.labelcolor": INK_2,
    "legend.handlelength": 1.6,
    "savefig.format": "pdf",
    "savefig.dpi": 300,
    "savefig.bbox": "tight",
    "pdf.fonttype": 42,  # embed TrueType, as journals (e.g. IEEE) require
    "svg.fonttype": "none",
}


def save_capture(name: str, x, fs: float = 1.0, **meta) -> Path:
    """Save signal `x` (real or complex) for plotting. `meta` values are shown in the title.
    Inside a sim, writes to $CAPTURE_DIR (set by dsplib.sim.run)."""
    path = Path(os.environ.get("CAPTURE_DIR", ".")) / f"{name}.npz"
    np.savez(path, x=np.asarray(x), fs=fs, meta=json.dumps(meta, default=str))
    return path


def plot_enabled() -> bool:
    return bool(os.environ.get("PLOT")) and not os.environ.get("CI")


def _fmt(v) -> str:
    return f"{v:.4g}" if isinstance(v, float) else str(v)


def _legend(ax) -> None:
    # Above the plot, right-aligned on the title row, so it never covers data. Thin data
    # strokes make unreadable swatches, so thicken only the swatches.
    leg = ax.legend(
        loc="lower right", bbox_to_anchor=(1, 1), ncols=4, borderaxespad=0.3
    )
    for line in leg.get_lines():
        line.set_linewidth(2)


def show(paths) -> None:
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    from matplotlib.ticker import EngFormatter, MaxNLocator

    with mpl.rc_context({**STYLE, "axes.prop_cycle": mpl.cycler(color=COLORS)}):
        for path in paths:
            d = np.load(path)
            x, fs = d["x"], float(d["fs"])
            meta = json.loads(str(d["meta"]))
            fig, (ax_t, ax_f) = plt.subplots(2, 1)
            fig.suptitle(
                "  ·  ".join(
                    [f"{Path(path).parent.name}/{Path(path).stem}"]
                    + [f"{k} {_fmt(v)}" for k, v in meta.items()]
                ),
                x=0.01,
                ha="left",
                fontsize=8.5,
                color=MUTED,
            )

            t = np.arange(min(len(x), TIME_SAMPLES)) / fs
            if np.iscomplexobj(x):
                ax_t.plot(t, x.real[: len(t)], label="I")
                ax_t.plot(t, x.imag[: len(t)], label="Q")
                _legend(ax_t)
            else:
                ax_t.plot(t, x[: len(t)])
            ax_t.set(
                title="Time domain",
                xlabel="Time" if fs != 1 else "Sample",
                ylabel="Amplitude",
            )

            f, p = spectrum_db(x, fs)
            k, s = carrier_and_spur(p, np.iscomplexobj(x))
            ax_f.plot(f, p, lw=0.5)  # thinnest stroke for the dense noise floor
            # Max spur: dashed reference across the band, direct-labeled instead of a legend.
            ax_f.axhline(p[s], color=INK_2, lw=0.7, ls=(0, (4, 3)))
            ax_f.plot(f[s], p[s], "o", ms=5, mfc=INK_2, mec="white", mew=1.2)
            ax_f.text(
                0.995,
                p[s],
                f"max spur {p[s]:.1f} dBc".replace(
                    "-", "−"
                ),  # true minus, as on the axes
                transform=ax_f.get_yaxis_transform(),
                ha="right",
                va="bottom",
                fontsize=8,
                color=INK_2,
                bbox={"fc": "white", "ec": "none", "pad": 1.5},
            )
            # Floor at the noise (ignoring window nulls), rounded to a 10 dB grid line; peak at the top edge.
            floor = 10 * np.floor((np.percentile(p, 0.5) - 5) / 10)
            ax_f.set(
                title=f"Spectrum  ·  SFDR {p[k] - p[s]:.1f} dBc",
                xlabel="Frequency"
                if fs != 1
                else "Normalized frequency (cycles/sample)",
                ylabel="Power (dBc)",
                ylim=(floor, 0),
            )
            ax_f.yaxis.set_major_locator(
                MaxNLocator(steps=[1, 2, 5, 10])
            )  # 10/20 dB, never 25
            if fs != 1:
                ax_t.xaxis.set_major_formatter(EngFormatter(unit="s"))
                ax_f.xaxis.set_major_formatter(EngFormatter(unit="Hz"))
        plt.show()


if __name__ == "__main__":
    paths = [
        p
        for arg in sys.argv[1:]
        for p in (sorted(Path(arg).rglob("*.npz")) if Path(arg).is_dir() else [arg])
    ]
    if not paths:
        sys.exit("no captures found; run the testbench first")
    show(paths)
