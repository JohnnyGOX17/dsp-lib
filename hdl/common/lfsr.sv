// Galois (right-shift) LFSR, one shift per enabled cycle. POLY has bit (t-1) set for each
// tap t; the default is maximal length for WIDTH=32 (taps 32,22,2,1), override for others.
// Bit-exact model: python/src/dsplib/lfsr.py
module lfsr #(
    parameter int WIDTH = 32,
    parameter logic [WIDTH-1:0] POLY = 32'h8020_0003,
    parameter logic [WIDTH-1:0] SEED = 1  // must be nonzero
) (
    input  logic             clk,
    input  logic             rst,   // synchronous, active-high; loads SEED
    input  logic             en,
    output logic [WIDTH-1:0] state
);

    always_ff @(posedge clk) begin
        if (rst) state <= SEED;
        else if (en) state <= (state >> 1) ^ (state[0] ? POLY : '0);
    end

endmodule
