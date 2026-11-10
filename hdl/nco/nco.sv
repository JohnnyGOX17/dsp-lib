// Numerically Controlled Oscillator: phase accumulator into a quarter-wave sine ROM, with
// optional LFSR phase dither to break up phase-truncation spurs.
//   f_out = phase_inc * f_clk / 2**PHASE_W
// The ROM holds sin(pi/2 * (k + 0.5) / 2**ADDR_W): the half-LSB offset makes quadrant
// mirroring an exact address invert, and no entry is 0, so negation is symmetric.
// Bit-exact model: python/src/dsplib/nco.py
module nco #(
    parameter int PHASE_W = 32,  // phase accumulator width
    parameter int ADDR_W = 10,  // quarter-wave ROM address width; phase resolution ADDR_W+2
    parameter int OUT_W = 16,  // signed output width
    parameter bit DITHER = 1'b0,  // add LFSR dither below the phase truncation point
    parameter logic [31:0] LFSR_SEED = 32'd1
) (
    input  logic                      clk,
    input  logic                      rst,        // synchronous, active-high
    input  logic                      en,         // advance one sample
    input  logic        [PHASE_W-1:0] phase_inc,
    output logic                      valid,      // LATENCY cycles after en
    output logic signed [  OUT_W-1:0] cos_out,
    output logic signed [  OUT_W-1:0] sin_out
);

    localparam int P = ADDR_W + 2;  // truncated phase width
    localparam int TRUNC_W = PHASE_W - P;  // discarded phase bits
    localparam int LATENCY = 5;  // keep in sync with LATENCY in test_nco.py
    localparam int AMP = 2 ** (OUT_W - 1) - 1;
    localparam real PI = 3.141592653589793;

    if (DITHER && (TRUNC_W < 1 || TRUNC_W > 32)) begin : g_bad_params
        $error("DITHER needs 1 <= PHASE_W - (ADDR_W + 2) <= 32");
    end

    // Stage 0: phase accumulator; sample k uses the phase before its increment
    logic [PHASE_W-1:0] acc;
    logic [PHASE_W-1:0] dither;

    always_ff @(posedge clk) begin
        if (rst) acc <= '0;
        else if (en) acc <= acc + phase_inc;
    end

    if (DITHER) begin : g_dither
        logic [31:0] lfsr_state;
        lfsr #(
            .WIDTH(32),
            .SEED (LFSR_SEED)
        ) u_lfsr (
            .clk,
            .rst,
            .en,
            .state(lfsr_state)
        );
        assign dither = PHASE_W'(lfsr_state[TRUNC_W-1:0]);
    end else begin : g_no_dither
        assign dither = '0;
    end

    // Stage 1: dither and truncate
    logic [PHASE_W-1:0] phase_dith;
    logic [      P-1:0] phase;
    assign phase_dith = acc + dither;

    always_ff @(posedge clk) phase <= phase_dith[PHASE_W-1-:P];

    // Stage 2: quadrant -> ROM address mirror and output negate
    logic [ADDR_W-1:0] addr, sin_addr, cos_addr;
    logic [1:0] neg[3];  // {sin, cos} negate, delayed to line up with ROM output
    assign addr = phase[ADDR_W-1:0];

    always_ff @(posedge clk) begin
        sin_addr <= phase[ADDR_W] ? ~addr : addr;
        cos_addr <= phase[ADDR_W] ? addr : ~addr;
        neg[0]   <= {phase[P-1], phase[P-1] ^ phase[P-2]};
        neg[1]   <= neg[0];
        neg[2]   <= neg[1];
    end

    // Stages 3-4: ROM read with output register (maps to BRAM with DOA/DOB_REG)
    logic [OUT_W-2:0] rom[2**ADDR_W];  // magnitudes only; sign comes from the quadrant
    logic [OUT_W-2:0] sin_rd, cos_rd, sin_mag, cos_mag;

    initial begin
        real x;
        for (int k = 0; k < 2 ** ADDR_W; k++) begin
            x = AMP * $sin(PI / 2 * (k + 0.5) / 2 ** ADDR_W);
            rom[k] = (OUT_W - 1)'($rtoi($floor(x + 0.5)));
        end
    end

    always_ff @(posedge clk) begin
        sin_rd  <= rom[sin_addr];
        cos_rd  <= rom[cos_addr];
        sin_mag <= sin_rd;
        cos_mag <= cos_rd;
    end

    // Stage 5: apply quadrant sign
    always_ff @(posedge clk) begin
        sin_out <= neg[2][1] ? -$signed({1'b0, sin_mag}) : $signed({1'b0, sin_mag});
        cos_out <= neg[2][0] ? -$signed({1'b0, cos_mag}) : $signed({1'b0, cos_mag});
    end

    logic [LATENCY-1:0] valid_sr;

    always_ff @(posedge clk) begin
        if (rst) valid_sr <= '0;
        else valid_sr <= {valid_sr[LATENCY-2:0], en};
    end

    assign valid = valid_sr[LATENCY-1];

endmodule
