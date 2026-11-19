"""Where a block's files live. Shared by dsplib.sim (Verilator) and dsplib.synth (Vivado).

A block `<b>` is the directory hdl/<b>/; its sources are listed in hdl/<b>/files.f, one path
per line relative to the repo root. `#` and `//` start comments.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def hdl_dir(block: str) -> Path:
    return REPO / "hdl" / block


def sources(block: str) -> list[Path]:
    """Source files from hdl/<block>/files.f, in order."""
    paths = []
    for line in (hdl_dir(block) / "files.f").read_text().splitlines():
        line = line.split("#", 1)[0].split("//", 1)[0].strip()
        if line:
            paths.append(REPO / line)
    return paths
