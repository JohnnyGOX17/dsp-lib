# Non-project, out-of-context synthesis (+ place & route) of one dsp-lib block.
#
# Called by dsplib.synth (`just synth <block>`) from the run's output directory,
# build/<block>/synth/<tag>/:
#
#     vivado -mode batch -source synth.tcl -tclargs params.tcl
#
# params.tcl (written by dsplib.synth) sets: top part clock period generics sources impl.
# Writes reports, a checkpoint and result.json into the current directory. This script only
# drives Vivado and records what it built; pass/fail is decided in dsplib.synth.

source [lindex $argv 0]

# Out-of-context: no I/O buffers are inserted and ports are left unplaced, so the counts are
# the block alone. HD.CLK_SRC tells timing the clock arrives on a global buffer, as it will
# in a real design. Only reg-to-reg paths are timed (ports carry no I/O delays).
set fh [open clocks.xdc w]
puts $fh "create_clock -period $period -name $clock \[get_ports $clock\]"
puts $fh "set_property HD.CLK_SRC BUFGCTRL_X0Y0 \[get_ports $clock\]"
close $fh

read_verilog -sv $sources
read_xdc clocks.xdc

set synth_args [list -top $top -part $part -mode out_of_context]
foreach g $generics { lappend synth_args -generic $g }
synth_design {*}$synth_args

if {$impl} {
    opt_design
    place_design
    route_design
    set stage route
} else {
    set stage synth
}

report_utilization -file utilization.rpt
report_utilization -hierarchical -file utilization_hier.rpt
report_timing_summary -max_paths 10 -report_unconstrained -file timing.rpt
report_drc -name drc -file drc.rpt
write_checkpoint -force post_$stage.dcp

# ---- result.json ---------------------------------------------------------------------------

proc json_str {s} { return "\"[string map {\\ \\\\ \" \\\"} $s]\"" }

proc json_obj {d} {
    set items {}
    dict for {k v} $d { lappend items "[json_str $k]: $v" }
    return "{[join $items {, }]}"
}

proc json_num {v} { expr {$v eq "" ? "null" : $v} }

# Worst path of a type (setup/hold), or {} when nothing is constrained.
proc worst_path {type} {
    set p [get_timing_paths -quiet -max_paths 1 -nworst 1 -$type]
    if {[llength $p] == 0 || [get_property SLACK $p] eq ""} { return {} }
    return $p
}

set timing [dict create wns null whs null]
set setup [worst_path setup]
if {$setup ne {}} {
    dict set timing wns [get_property SLACK $setup]
    dict set timing startpoint [json_str [get_property STARTPOINT_PIN $setup]]
    dict set timing endpoint [json_str [get_property ENDPOINT_PIN $setup]]
    dict set timing logic_levels [get_property LOGIC_LEVELS $setup]
    dict set timing datapath_ns [json_num [get_property DATAPATH_DELAY $setup]]
}
set hold [worst_path hold]
if {$hold ne {}} { dict set timing whs [get_property SLACK $hold] }

# Leaf primitives by type (macro internals such as a RAM32M's RAMD32s are not double counted).
set prims [dict create]
foreach c [get_cells -quiet -hier -filter {IS_PRIMITIVE && PRIMITIVE_LEVEL != INTERNAL}] {
    dict incr prims [get_property REF_NAME $c]
}

# Hard-block configuration: evidence a block mapped as intended, not just that it used one.
set dsp_props {AREG BREG CREG MREG PREG USE_MULT USE_DPORT}
set bram_props {RAM_MODE READ_WIDTH_A READ_WIDTH_B DOA_REG DOB_REG}
set hard {}
foreach c [get_cells -quiet -hier -filter {REF_NAME =~ DSP48* || REF_NAME =~ RAMB*}] {
    set ref [get_property REF_NAME $c]
    set props [dict create]
    foreach p [expr {[string match DSP48* $ref] ? $dsp_props : $bram_props}] {
        dict set props $p [json_str [get_property -quiet $p $c]]
    }
    if {[string match RAMB* $ref]} {
        # A ROM whose contents failed to elaborate initializes to all zeros.
        set nonzero false
        foreach p [list_property $c INIT_*] {
            if {[regexp {'h0*[1-9A-Fa-f]} [get_property $p $c]]} { set nonzero true; break }
        }
        dict set props INIT [json_str [expr {$nonzero ? "nonzero" : "zero"}]]
    }
    lappend hard [json_obj [dict create \
        name [json_str $c] ref [json_str $ref] props [json_obj $props]]]
}

set drc [dict create]
foreach v [get_drc_violations -quiet -name drc] {
    dict incr drc [regsub {#.*} [get_property NAME $v] {}]
}

set result [dict create \
    vivado [json_str [version -short]] \
    part [json_str $part] \
    top [json_str $top] \
    stage [json_str $stage] \
    clock [json_str $clock] \
    period_ns $period \
    timing [json_obj $timing] \
    critical_warnings [get_msg_config -count -severity {CRITICAL WARNING}] \
    warnings [get_msg_config -count -severity WARNING] \
    primitives [json_obj $prims] \
    hard_blocks "\[[join $hard {, }]\]" \
    drc [json_obj $drc]]

set fh [open result.json w]
puts $fh [json_obj $result]
close $fh
