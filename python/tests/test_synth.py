"""dsplib.synth logic that needs no Vivado: report parsing, expectations, README updates."""

import pytest
from dsplib import blocks, synth

# Excerpt of a Vivado 2025.1 post-route report_utilization (nco, xc7z010clg225-1). Section 2
# repeats "LUT as Memory" (edited to 99 here) to check the first row of each name wins.
UTIL_RPT = """\
1. Slice Logic
--------------

+----------------------------+------+-------+------------+-----------+-------+
|          Site Type         | Used | Fixed | Prohibited | Available | Util% |
+----------------------------+------+-------+------------+-----------+-------+
| Slice LUTs                 |   75 |     0 |          0 |     17600 |  0.43 |
|   LUT as Logic             |   73 |     0 |          0 |     17600 |  0.41 |
|   LUT as Memory            |    2 |     0 |          0 |      6000 |  0.03 |
|     LUT as Distributed RAM |    0 |     0 |            |           |       |
|     LUT as Shift Register  |    2 |     0 |            |           |       |
| Slice Registers            |  113 |     0 |          0 |     35200 |  0.32 |
+----------------------------+------+-------+------------+-----------+-------+

2. Slice Logic Distribution
---------------------------

| LUT as Memory                              |   99 |     0 |          0 |      6000 |  0.03 |

3. Memory
---------

+-------------------+------+-------+------------+-----------+-------+
|     Site Type     | Used | Fixed | Prohibited | Available | Util% |
+-------------------+------+-------+------------+-----------+-------+
| Block RAM Tile    |  0.5 |     0 |          0 |        60 |  0.83 |
|   RAMB36/FIFO*    |    0 |     0 |          0 |        60 |  0.00 |
|   RAMB18          |    1 |     0 |          0 |       120 |  0.83 |
+-------------------+------+-------+------------+-----------+-------+

4. DSP
------

+-----------+------+-------+------------+-----------+-------+
| Site Type | Used | Fixed | Prohibited | Available | Util% |
+-----------+------+-------+------------+-----------+-------+
| DSPs      |    0 |     0 |          0 |        80 |  0.00 |
+-----------+------+-------+------------+-----------+-------+
"""


def result(**over) -> dict:
    """A measure()-shaped result, as for nco dither0."""
    res = {
        "vivado": "2025.1",
        "part": "xc7z010clg225-1",
        "top": "nco",
        "stage": "route",
        "clock": "clk",
        "period_ns": 4.0,
        "timing": {
            "wns": 0.68,
            "whs": 0.149,
            "startpoint": "neg_reg[2][0]/C",
            "endpoint": "cos_out_reg[15]/D",
            "logic_levels": 5,
            "datapath_ns": 3.048,
        },
        "critical_warnings": 0,
        "warnings": 37,
        "primitives": {"LUT2": 81, "FDRE": 113, "CARRY4": 16, "RAMB18E1": 1},
        "hard_blocks": [
            {
                "name": "rom_reg",
                "ref": "RAMB18E1",
                "props": {"RAM_MODE": "TDP", "DOA_REG": "1", "INIT": "nonzero"},
            }
        ],
        "drc": {"ZPS7-1": 1},
        "util": synth.parse_utilization(UTIL_RPT),
        "fmax_mhz": 1000 / (4.0 - 0.68),
    }
    res.update(over)
    return res


def cfg(**over) -> dict:
    return {**synth.DEFAULTS, "tag": "t", "parameters": {"N": 4}, **over}


def failed(checks) -> set[str]:
    return {name for name, ok, _ in checks if not ok}


def test_parse_utilization():
    u = synth.parse_utilization(UTIL_RPT)
    assert u["lut"] == {"used": 75, "available": 17600, "util": 0.43}
    assert u["lutram"]["used"] == 2  # first row wins over section 2's 99
    assert u["ff"]["used"] == 113
    assert u["bram"] == {"used": 0.5, "available": 60, "util": 0.83}
    assert u["dsp"]["used"] == 0


def test_parse_utilization_post_synth_footnote_and_tiny_util():
    u = synth.parse_utilization("| Slice LUTs*  |    1 |  0 |  0 | 17600 | <0.01 |")
    assert u["lut"] == {"used": 1, "available": 17600, "util": 0.01}


def test_configs_defaults_overrides_and_expect_merge():
    spec = {
        "period_ns": 5.0,
        "expect": {"DSP48E1": 0, "lut": {"max": 10}},
        "config": [
            {"tag": "a"},
            {"tag": "b", "period_ns": 3.0, "expect": {"lut": {"max": 20}}},
        ],
    }
    a, b = synth.configs("x", spec)
    assert a["part"] == "xc7z010clg225-1" and a["period_ns"] == 5.0
    assert a["expect"] == {"DSP48E1": 0, "lut": {"max": 10}}
    assert b["period_ns"] == 3.0
    assert b["expect"] == {"DSP48E1": 0, "lut": {"max": 20}}
    with pytest.raises(synth.SynthError, match="duplicate"):
        synth.configs("x", {"config": [{"tag": "a"}, {"tag": "a"}]})


def test_check_expectations():
    ok = cfg(
        expect={"RAMB18E1": 1, "DSP48E1": 0, "lut": {"max": 90}, "ff": {"min": 100}}
    )
    assert failed(synth.check(ok, result())) == set()

    bad = cfg(
        expect={"RAMB18E1": 2, "DSP48E1": 1, "lut": {"max": 50}, "bram": {"min": 1}}
    )
    assert failed(synth.check(bad, result())) == {"RAMB18E1", "DSP48E1", "lut", "bram"}

    with pytest.raises(synth.SynthError, match="unknown expect key"):
        synth.check(cfg(expect={"luts": 1}), result())


def test_check_timing_warnings_and_drc():
    timing = {**result()["timing"], "wns": -0.1}
    res = result(timing=timing, critical_warnings=1, drc={"DPOP-1": 2, "DPIP-1": 1})
    assert failed(synth.check(cfg(), res)) == {
        "timing",
        "critical warnings",
        "DRC DPOP-1",
        "DRC DPIP-1",
    }
    relaxed = cfg(allow_drc=["DPIP-1"], max_critical_warnings=1)
    assert failed(synth.check(relaxed, res)) == {"timing", "DRC DPOP-1"}

    no_paths = result(timing={"wns": None, "whs": None}, fmax_mhz=None)
    assert failed(synth.check(cfg(), no_paths)) == set()


def test_readme_section_and_update(tmp_path):
    section = synth.readme_section("nco", [(cfg(tag="dither0"), result())], "abc123")
    assert "| `dither0` | `N=4` | 75 (0.43%) | 2 | 113 (0.32%) | 16 |" in section
    assert "+0.680 | 301 |" in section
    assert "1× RAMB18E1 `RAM_MODE=TDP DOA_REG=1 INIT=nonzero`" in section

    readme = tmp_path / "README.md"
    readme.write_text("# nco\n\nIntro.\n")
    synth.update_readme(readme, section)  # no markers: appends a Synthesis section
    assert readme.read_text().startswith(
        "# nco\n\nIntro.\n\n## Synthesis\n\n<!-- synth:begin"
    )

    readme.write_text(readme.read_text() + "\n## After\n")
    synth.update_readme(
        readme, section.replace("abc123", "def456")
    )  # replaces in place
    text = readme.read_text()
    assert "abc123" not in text and text.count("synth:begin") == 1
    assert text.startswith("# nco\n\nIntro.\n\n## Synthesis\n") and text.endswith(
        "\n## After\n"
    )


def test_stale_tracks_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(blocks, "REPO", tmp_path)
    monkeypatch.setattr(synth, "REPO", tmp_path)
    d = tmp_path / "hdl" / "foo"
    d.mkdir(parents=True)
    (d / "foo.sv").write_text("module foo; endmodule\n")
    (d / "files.f").write_text("# sources\nhdl/foo/foo.sv  // the block\n")
    (d / "synth.toml").write_text("period_ns = 4.0\n")
    assert synth.sources("foo") == [d / "foo.sv"]
    assert synth.stale() == [("foo", "no synthesis results in README.md")]

    synth.update_readme(
        d / "README.md",
        synth.readme_section("foo", [(cfg(), result())], synth.src_hash("foo")),
    )
    assert synth.stale() == []

    (d / "foo.sv").write_text("module foo; /* edit */ endmodule\n")
    assert [b for b, _ in synth.stale()] == ["foo"]
