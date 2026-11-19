"""Vivado synthesis checks for one block (local only; Vivado's settings64.sh sourced first):

    just synth nco                     # every [[config]] in hdl/nco/synth.toml
    just synth nco --tag dither1       # one config
    just synth nco --synth-only        # skip place & route (faster, optimistic timing)
    just synth-check                   # no Vivado: which block READMEs are out of date

hdl/<block>/synth.toml gives the target clock and parameter sets, each with expected
primitive counts. For each config, scripts/vivado/synth.tcl runs a non-project,
out-of-context synth + place & route on the PLUTO's Zynq-7010 into build/<block>/synth/<tag>/.
The results are checked against the expectations and, when a full run of every config passes,
written into the generated section of hdl/<block>/README.md. That section records a hash of
the block's sources, so `--check` can flag stale results without Vivado.

synth.toml keys (top level, any of which a [[config]] may override; `expect` merges):
    part          default xc7z010clg225-1 (ADALM PLUTO)
    clock         clock port name, default "clk"
    period_ns     target clock period; timing must be met (WNS >= 0)
    allow_drc     DRC rules to tolerate out of FORBID_DRC
    max_critical_warnings   default 0
[[config]] keys: tag, parameters (HDL generics), expect. `expect` maps an uppercase primitive
REF_NAME (DSP48E1, RAMB18E1, ...) or a lowercase utilization group (lut, lutram, ff, bram, dsp)
to an exact count or a {min, max} range.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

from dsplib.blocks import REPO, hdl_dir, sources

TCL = REPO / "scripts" / "vivado" / "synth.tcl"
DEFAULTS = {
    "part": "xc7z010clg225-1",
    "clock": "clk",
    "period_ns": 4.0,
    "allow_drc": [],
    "max_critical_warnings": 0,
}
# DSP48 pipelining advisories: an input (DPIP-1), P (DPOP-1) or M (DPOP-2) register unused.
FORBID_DRC = ("DPIP-1", "DPOP-1", "DPOP-2")
# report_utilization summary rows, by the lowercase name used in `expect`.
UTIL_ROWS = {
    "lut": "Slice LUTs",
    "lutram": "LUT as Memory",
    "ff": "Slice Registers",
    "bram": "Block RAM Tile",
    "dsp": "DSPs",
}
BEGIN_RE = re.compile(r"<!-- synth:begin(?: hash=(\w+))? -->")
END = "<!-- synth:end -->"


class SynthError(Exception):
    pass


# ---- block files ------------------------------------------------------------------------------


def load(block: str) -> dict:
    path = hdl_dir(block) / "synth.toml"
    if not path.exists():
        raise SynthError(f"{path.relative_to(REPO)} not found")
    return tomllib.loads(path.read_text())


def configs(block: str, spec: dict | None = None) -> list[dict]:
    """Each [[config]] with top-level keys and DEFAULTS filled in; `expect` tables merge."""
    spec = spec if spec is not None else load(block)
    top = {**DEFAULTS, **{k: v for k, v in spec.items() if k != "config"}}
    out = [
        {**top, **c, "expect": {**top.get("expect", {}), **c.get("expect", {})}}
        for c in spec.get("config", [{"tag": "default"}])
    ]
    tags = [c["tag"] for c in out]
    if len(set(tags)) != len(tags):
        raise SynthError(f"duplicate config tags in {block}/synth.toml: {tags}")
    return out


def digest(paths) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(str(Path(p).relative_to(REPO)).encode() + b"\0" + Path(p).read_bytes())
    return h.hexdigest()[:12]


def src_hash(block: str) -> str:
    """Hash of everything that determines the synth result: sources and synth.toml."""
    return digest([*sources(block), hdl_dir(block) / "synth.toml"])


# ---- running Vivado ---------------------------------------------------------------------------


def _tcl_list(items) -> str:
    return "[list " + " ".join("{" + str(i) + "}" for i in items) + "]"


def _generic(k: str, v) -> str:
    return f"{k}={int(v)}" if isinstance(v, bool) else f"{k}={v}"


def run_vivado(block: str, cfg: dict, synth_only: bool = False) -> Path:
    """Synthesize (and unless synth_only, place & route) one config. Returns its output dir."""
    out = REPO / "build" / block / "synth" / cfg["tag"]
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / "params.tcl").write_text(
        "\n".join(
            [
                f"set top {{{cfg.get('top', block)}}}",
                f"set part {{{cfg['part']}}}",
                f"set clock {{{cfg['clock']}}}",
                f"set period {cfg['period_ns']}",
                f"set impl {0 if synth_only else 1}",
                "set generics "
                + _tcl_list(
                    _generic(k, v) for k, v in cfg.get("parameters", {}).items()
                ),
                "set sources " + _tcl_list(sources(block)),
                "",
            ]
        )
    )
    cmd = ["vivado", "-mode", "batch", "-nojournal", "-notrace", "-log", "vivado.log"]
    cmd += ["-source", str(TCL), "-tclargs", "params.tcl"]
    proc = subprocess.run(
        cmd, cwd=out, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    )
    if proc.returncode != 0 or not (out / "result.json").exists():
        log = out / "vivado.log"
        errors = [ln for ln in log.read_text().splitlines() if ln.startswith("ERROR")]
        raise SynthError(
            f"Vivado failed for {block}/{cfg['tag']}; see {log.relative_to(REPO)}\n"
            + "\n".join(errors[:10])
        )
    return out


# ---- results ----------------------------------------------------------------------------------


def parse_utilization(text: str) -> dict:
    """Summary rows of a report_utilization file: {group: {used, available, util}}.

    Rows look like `| Slice LUTs* |   71 |  0 |  0 | 17600 |  0.40 |`; the first row of each
    name wins (later sections repeat some names), and a trailing `*` (footnote) is ignored.
    """
    wanted = {v: k for k, v in UTIL_ROWS.items()}
    found = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        name = cells[0].rstrip("*").strip()
        if name in wanted and wanted[name] not in found:
            try:
                used, avail = float(cells[1]), float(cells[-2])
                util = float(cells[-1].lstrip("<"))
            except ValueError:
                continue
            found[wanted[name]] = {
                "used": int(used) if used.is_integer() else used,
                "available": int(avail),
                "util": util,
            }
    return found


def measure(out: Path) -> dict:
    """result.json from synth.tcl plus the utilization summary."""
    res = json.loads((out / "result.json").read_text())
    res["util"] = parse_utilization((out / "utilization.rpt").read_text())
    wns = res["timing"]["wns"]
    res["fmax_mhz"] = None if wns is None else 1000 / (res["period_ns"] - wns)
    return res


def _value(key: str, res: dict):
    if key.isupper():
        return res["primitives"].get(key, 0)
    if key not in UTIL_ROWS:
        raise SynthError(
            f"unknown expect key {key!r}: use a primitive REF_NAME or one of {list(UTIL_ROWS)}"
        )
    return res["util"].get(key, {}).get("used", 0)


def check(cfg: dict, res: dict) -> list[tuple[str, bool, str]]:
    """Every check for one config as (name, passed, detail)."""
    out = []
    for key, want in cfg.get("expect", {}).items():
        got = _value(key, res)
        if isinstance(want, dict):
            lo, hi = want.get("min", float("-inf")), want.get("max", float("inf"))
            ok = lo <= got <= hi
            rng = " ".join(f"{k} {want[k]}" for k in ("min", "max") if k in want)
            out.append((key, ok, f"{got} ({rng})"))
        else:
            out.append((key, got == want, f"{got} (expect {want})"))

    wns = res["timing"]["wns"]
    if wns is None:
        out.append(("timing", True, "no constrained reg-to-reg paths"))
    else:
        out.append(
            (
                "timing",
                wns >= 0,
                f"WNS {wns:+.3f} ns at {cfg['period_ns']} ns, Fmax ~{res['fmax_mhz']:.0f} MHz",
            )
        )

    cw, max_cw = res["critical_warnings"], cfg["max_critical_warnings"]
    out.append(("critical warnings", cw <= max_cw, f"{cw} (max {max_cw})"))

    for rule in FORBID_DRC:
        if rule not in cfg["allow_drc"]:
            n = res["drc"].get(rule, 0)
            out.append((f"DRC {rule}", n == 0, f"{n} violations"))
    return out


# ---- README -----------------------------------------------------------------------------------


def _pct(res: dict, key: str) -> str:
    u = res["util"].get(key)
    return "–" if u is None else f"{u['used']} ({u['util']:.2f}%)"


def _hard_summary(res: dict) -> str:
    """Distinct hard-block configurations, e.g. `1× RAMB18E1 (RAM_MODE=TDP ...)`."""
    kinds = Counter(
        (hb["ref"], tuple(f"{k}={v}" for k, v in hb["props"].items()))
        for hb in res["hard_blocks"]
    )
    return "; ".join(
        f"{n}× {ref} `{' '.join(props)}`" for (ref, props), n in kinds.items()
    )


def readme_section(block: str, runs: list[tuple[dict, dict]], hash_: str) -> str:
    """Generated synthesis section for one block: runs are (config, result) pairs."""
    cfg0, res0 = runs[0]
    stage = "synth + place & route" if res0["stage"] == "route" else "synth only"
    lines = [
        f"<!-- synth:begin hash={hash_} -->",
        f"<!-- Generated by `just synth {block}`; edits between these markers are overwritten. -->",
        "",
        (
            f"Vivado {res0['vivado']} · `{res0['part']}` · out-of-context {stage} · "
            f"target {1000 / cfg0['period_ns']:.0f} MHz "
            f"(`{res0['clock']}` {cfg0['period_ns']} ns) · source hash `{hash_}`"
        ),
        "",
        (
            "| Config | Parameters | Slice LUTs | LUTRAM/SRL | FFs | CARRY4 | BRAM tiles | DSPs "
            "| WNS (ns) | Fmax (MHz) |"
        ),
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for cfg, res in runs:
        params = " ".join(_generic(k, v) for k, v in cfg.get("parameters", {}).items())
        wns, fmax = res["timing"]["wns"], res["fmax_mhz"]
        lines.append(
            f"| `{cfg['tag']}` | `{params}` | {_pct(res, 'lut')} | "
            f"{res['util'].get('lutram', {}).get('used', 0)} | {_pct(res, 'ff')} | "
            f"{res['primitives'].get('CARRY4', 0)} | {_pct(res, 'bram')} | {_pct(res, 'dsp')} | "
            + ("– | – |" if wns is None else f"{wns:+.3f} | {fmax:.0f} |")
        )
    lines += ["", "Hard blocks and worst setup path:", ""]
    for cfg, res in runs:
        t = res["timing"]
        path = (
            f"`{t['startpoint']}` → `{t['endpoint']}`, {t['logic_levels']} logic levels"
            if t["wns"] is not None
            else "none"
        )
        lines.append(
            f"- `{cfg['tag']}`: {_hard_summary(res) or 'no BRAM/DSP'}; path {path}"
        )
    lines += [
        "",
        (
            "Fmax ≈ 1/(T − WNS) is a lower bound: place & route stops improving once the "
            "target is met. Only reg-to-reg paths are timed; ports have no I/O constraints."
        ),
        END,
    ]
    return "\n".join(lines)


def update_readme(path: Path, section: str) -> None:
    """Replace the generated section in `path`, or append one under a `## Synthesis` heading."""
    text = path.read_text() if path.exists() else ""
    m = BEGIN_RE.search(text)
    end = text.find(END, m.end()) if m else -1
    if m and end >= 0:
        text = text[: m.start()] + section + text[end + len(END) :]
    else:
        text = (
            text.rstrip("\n")
            + ("\n\n" if text else "")
            + "## Synthesis\n\n"
            + section
            + "\n"
        )
    path.write_text(text)


def readme_hash(block: str) -> str | None:
    path = hdl_dir(block) / "README.md"
    m = BEGIN_RE.search(path.read_text()) if path.exists() else None
    return m.group(1) if m else None


def stale() -> list[tuple[str, str]]:
    """(block, reason) for every block with a synth.toml whose README results are not current."""
    out = []
    for toml in sorted((REPO / "hdl").glob("*/synth.toml")):
        block = toml.parent.name
        recorded = readme_hash(block)
        if recorded is None:
            out.append((block, "no synthesis results in README.md"))
        elif recorded != src_hash(block):
            out.append((block, f"sources changed since synth (README {recorded})"))
    return out


# ---- CLI --------------------------------------------------------------------------------------


def run(block: str, tags: list[str] | None = None, synth_only: bool = False) -> bool:
    """Synthesize and check `block`; on a full passing run, update its README. True if passed."""
    if shutil.which("vivado") is None:
        raise SynthError(
            "vivado is not on PATH: first run `source <install>/<version>/Vivado/settings64.sh`"
        )
    hash_ = src_hash(block)
    cfgs = configs(block)
    if tags:
        unknown = set(tags) - {c["tag"] for c in cfgs}
        if unknown:
            raise SynthError(
                f"no config tagged {sorted(unknown)} in {block}/synth.toml"
            )
        cfgs = [c for c in cfgs if c["tag"] in tags]

    runs, passed = [], True
    for i, cfg in enumerate(cfgs, 1):
        flow = "synth" if synth_only else "synth + place & route"
        log = (
            REPO / "build" / block / "synth" / cfg["tag"] / "vivado.log"
        ).relative_to(REPO)
        print(
            f"[{i}/{len(cfgs)}] {block}/{cfg['tag']}: {flow} on {cfg['part']} (log: {log})"
        )
        t0 = time.monotonic()
        res = measure(run_vivado(block, cfg, synth_only))
        print(f"      done in {time.monotonic() - t0:.0f} s")
        for name, ok, detail in check(cfg, res):
            print(f"      {'✅' if ok else '❌'} {name:<18} {detail}")
            passed &= ok
        runs.append((cfg, res))

    readme = (hdl_dir(block) / "README.md").relative_to(REPO)
    if not passed:
        print(f"FAILED: {readme} not updated; reports in build/{block}/synth/")
    elif tags or synth_only:
        print(f"passed; {readme} is only updated by a full run (no --tag/--synth-only)")
    else:
        update_readme(REPO / readme, readme_section(block, runs, hash_))
        print(f"passed; updated {readme}")
    return passed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m dsplib.synth", description=__doc__.split("\n")[0]
    )
    ap.add_argument("block", nargs="?", help="block name (directory under hdl/)")
    ap.add_argument("--tag", action="append", help="only this config (repeatable)")
    ap.add_argument("--synth-only", action="store_true", help="skip place & route")
    ap.add_argument("--check", action="store_true", help="report stale README results")
    args = ap.parse_args(argv)
    try:
        if args.check:
            bad = stale()
            for block, reason in bad:
                print(f"{block}: {reason}; rerun `just synth {block}`")
            if not bad:
                print("all block synthesis results are current")
            return 1 if bad else 0
        if not args.block:
            ap.error("block is required (or use --check)")
        return 0 if run(args.block, args.tag, args.synth_only) else 1
    except SynthError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
