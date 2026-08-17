/*
 * hexengine — portable reference implementation of the per-string pattern engine.
 *
 * Deliberately plain C99 with no vendor headers, no floats in the hot path
 * option, and no I/O. The entire platform dependency is the four functions in
 * the "platform shim" block at the bottom, which is what makes the controller
 * choice deferrable: the same file runs on RP2350, STM32, Teensy, or on a host
 * under the simulator.
 *
 * Build the self-test with:
 *     cc -O2 -DHEXENGINE_SELFTEST -o hexengine hexengine.c -lm && ./hexengine
 */

#include <stdint.h>
#include <string.h>

#define NSTR        6
#define TBL_BITS    10
#define TBL         (1u << TBL_BITS)          /* 1024-entry shape tables      */
#define MAX_MODS    8
#define FS_CTRL     32000u                    /* control frame rate, Hz       */

/* Decibels are carried as Q8.8 signed: 1 dB = 256. Range +-128 dB.          */
typedef int16_t db_t;
#define DB(x)       ((db_t)((x) * 256.0f))
#define DB_FLOOR    DB(-60.0f)
#define DB_CEIL     DB(  6.0f)

typedef enum { MOD_PHASE, MOD_ROW, MOD_POLY } mod_mode_t;

#define MAX_ROW_LEN 32

typedef struct {
    mod_mode_t mode;
    uint8_t    enabled;
    uint8_t    interpolate;                   /* PHASE mode: lerp the table   */
    uint8_t    invert;                        /* use (1 - table) instead      */
    uint32_t   phase;                         /* 32-bit accumulator           */
    uint32_t   inc;                           /* phase per frame              */
    uint32_t   spread;                        /* per-string phase offset      */
    db_t       depth;                         /* attenuation at table == 1    */
    const uint16_t *table;                    /* PHASE: 0..65535, TBL entries */
    const uint8_t  *rows;                     /* ROW:   NSTR * nsteps, 0/1    */
    uint8_t    nsteps;
    /* POLY: one shared step clock, each row loops at its own length. Six
     * coprime lengths give lcm(...) steps before repeating — {5,7,4,3,8,6}
     * is 840 steps, 105 s at 8 steps/s, against 2 s for a fixed 16-step row. */
    const uint8_t *poly_rows[NSTR];
    uint8_t    poly_len[NSTR];
    uint32_t   step_count;
    uint8_t    only;                          /* 0xFF = all strings           */
} mod_t;

typedef struct {
    db_t     calib[NSTR];                     /* pattern 0 — the balance      */
    db_t     sense[NSTR];                     /* gate / swell / comp / duck   */
    mod_t    mod[MAX_MODS];
    /* affine map from dB to DAC code — the ONLY element-specific numbers.
     * Set from the two resistors in the CV divider. SSI2164 defaults below.  */
    int32_t  code_per_db;                     /* Q8: DAC LSBs per dB          */
    int32_t  code_at_0db;
    uint16_t code_max;
} engine_t;

/* ------------------------------------------------------------------------ */

static inline uint16_t tbl_read(const mod_t *m, uint32_t ph)
{
    uint32_t i0 = ph >> (32 - TBL_BITS);
    uint16_t v;
    if (m->interpolate) {
        uint32_t frac = (ph << TBL_BITS) >> 16;          /* Q16 fraction     */
        uint32_t i1   = (i0 + 1u) & (TBL - 1u);
        uint32_t a = m->table[i0], b = m->table[i1];
        v = (uint16_t)((a * (65536u - frac) + b * frac) >> 16);
    } else {
        v = m->table[i0];
    }
    return m->invert ? (uint16_t)(65535u - v) : v;
}

void engine_set_rate(mod_t *m, float hz)
{
    m->inc = (uint32_t)((double)hz * 4294967296.0 / (double)FS_CTRL + 0.5);
}

void engine_set_spread(mod_t *m, float degrees)
{
    m->spread = (uint32_t)((double)degrees / 360.0 * 4294967296.0);
}

/*
 * One control frame. Fills code[NSTR] with DAC codes.
 *
 * The whole engine is this: decibels add, because the VCA's control port is
 * dB-linear. Pattern 0 is the constant term. Everything else is a term.
 */
void engine_frame(engine_t *e, uint16_t code[NSTR])
{
    db_t db[NSTR];
    for (int n = 0; n < NSTR; n++)
        db[n] = e->calib[n] - e->sense[n];

    for (int k = 0; k < MAX_MODS; k++) {
        mod_t *m = &e->mod[k];
        if (!m->enabled) continue;

        if (m->mode == MOD_PHASE) {
            uint32_t ph = m->phase;
            for (int n = 0; n < NSTR; n++, ph += m->spread) {
                if (m->only != 0xFF && m->only != n) continue;
                /* depth * table/65535, in Q8.8 */
                db[n] -= (db_t)(((int32_t)m->depth * tbl_read(m, ph)) >> 16);
            }
        } else if (m->mode == MOD_ROW) {
            uint32_t step = ((uint64_t)m->phase * m->nsteps) >> 32;
            for (int n = 0; n < NSTR; n++) {
                if (m->only != 0xFF && m->only != n) continue;
                if (!m->rows[n * m->nsteps + step])
                    db[n] -= m->depth;
            }
        } else {                              /* MOD_POLY                     */
            uint32_t before = m->phase;
            for (int n = 0; n < NSTR; n++) {
                if (m->only != 0xFF && m->only != n) continue;
                if (!m->poly_rows[n][m->step_count % m->poly_len[n]])
                    db[n] -= m->depth;
            }
            /* inc is one full wrap per step, so a wrap advances the clock */
            if (before + m->inc < before) m->step_count++;
        }
        m->phase += m->inc;                   /* wraps naturally at 2^32      */
    }

    for (int n = 0; n < NSTR; n++) {
        if (db[n] < DB_FLOOR) db[n] = DB_FLOOR;
        if (db[n] > DB_CEIL)  db[n] = DB_CEIL;
        int32_t c = e->code_at_0db + ((e->code_per_db * db[n]) >> 16);
        if (c < 0) c = 0;
        if (c > e->code_max) c = e->code_max;
        code[n] = (uint16_t)c;
    }
}

void engine_init(engine_t *e)
{
    memset(e, 0, sizeof(*e));
    for (int n = 0; n < NSTR; n++) e->mod[n].only = 0xFF;
    for (int k = 0; k < MAX_MODS; k++) e->mod[k].only = 0xFF;
    /* DAC7568, 12-bit, 0-5 V, into a divider giving 33 mV/dB at the VCA.
     * 33 mV/dB / (5 V / 4096) = 27.03 LSB per dB. Negative: +CV = attenuate. */
    e->code_per_db = (int32_t)(-27.03f * 256.0f);      /* Q8 */
    e->code_at_0db = 2048;                             /* mid-scale = 0 dB   */
    e->code_max    = 4095;
}

/* ------------------------------------------------------------------------ *
 * Platform shim — the entire porting surface. Implement these four and the
 * engine runs anywhere.
 *
 *   hex_dac_write_block(const uint16_t *codes, int nframes)
 *       Hand a block of NSTR*nframes codes to a DMA'd, timer-triggered SPI
 *       stream. Must be hardware-timed; never bit-banged from an ISR.
 *   hex_adc_read(uint16_t *six)      six envelope-detector channels
 *   hex_millis(void)                 for the UI and tap tempo only
 *   hex_midi_poll(void)              clock, CC, notes
 * ------------------------------------------------------------------------ */

#ifdef HEXENGINE_SELFTEST
#include <stdio.h>
#include <math.h>

static uint16_t sine_tbl[TBL];

int main(void)
{
    for (unsigned i = 0; i < TBL; i++)
        sine_tbl[i] = (uint16_t)(65535.0 * (0.5 - 0.5 * cos(2 * M_PI * i / TBL)));

    engine_t e; engine_init(&e);
    mod_t *m = &e.mod[0];
    m->mode = MOD_PHASE; m->enabled = 1; m->interpolate = 1;
    m->table = sine_tbl; m->depth = DB(14.0f);
    engine_set_rate(m, 5.0f);
    engine_set_spread(m, 60.0f);

    /* one second of frames; track the summed linear gain */
    double gmin = 1e9, gmax = -1e9, dbmin = 1e9, dbmax = -1e9;
    uint16_t code[NSTR];
    for (unsigned f = 0; f < FS_CTRL; f++) {
        engine_frame(&e, code);
        double sum = 0;
        for (int n = 0; n < NSTR; n++) {
            double d = (code[n] - (double)e.code_at_0db) / (e.code_per_db / 256.0);
            if (d < dbmin) dbmin = d;
            if (d > dbmax) dbmax = d;
            sum += pow(10.0, d / 20.0);
        }
        if (f > 100) { if (sum < gmin) gmin = sum; if (sum > gmax) gmax = sum; }
    }
    printf("per-string dB range : %.2f .. %.2f  (expect -14.00 .. 0.00)\n", dbmin, dbmax);
    printf("summed level swing  : %.2f dB       (expect ~0.00 at spread 360/6)\n",
           20 * log10(gmax / gmin));

    engine_set_spread(m, 0.0f);
    gmin = 1e9; gmax = -1e9;
    for (unsigned f = 0; f < FS_CTRL; f++) {
        engine_frame(&e, code);
        double sum = 0;
        for (int n = 0; n < NSTR; n++)
            sum += pow(10.0, ((code[n] - (double)e.code_at_0db) / (e.code_per_db / 256.0)) / 20.0);
        if (f > 100) { if (sum < gmin) gmin = sum; if (sum > gmax) gmax = sum; }
    }
    printf("summed level swing  : %.2f dB       (expect ~14.00 at spread 0)\n",
           20 * log10(gmax / gmin));
    return 0;
}
#endif