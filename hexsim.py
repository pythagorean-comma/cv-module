#!/usr/bin/env python3
"""
hexsim — offline simulator for the Option B per-string pattern engine.

Purpose: answer the musical go/no-go before any hardware exists. Runs the same
engine structure the firmware would run (phase accumulators, shape tables,
dB-domain summing, control-rate quantisation, CV smoothing) over six string
signals, and renders the mono sum.

It also models the two things most likely to spoil it on the bench — VCA control
feedthrough and on-die channel crosstalk — so they can be auditioned rather than
argued about.

Six-channel source: either synthesised (Karplus-Strong, default) or a real
recording off the Nexus. To use real stems, pass a 6-channel WAV:

    python3 hexsim.py --stems my-hex-recording.wav --out demos/

Everything in the engine is deliberately written the way the firmware would be:
32-bit phase accumulators, integer phase offsets, decibels added as scalars.
The numpy vectorisation is over time only, never over the structure.
"""

import argparse
import os
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, lfilter

# ----------------------------------------------------------------------------
# Rates. FS_CTRL is the control frame rate from the design doc; the audio rate
# is only the simulator's rendering rate and has no hardware counterpart.
# ----------------------------------------------------------------------------
FS_AUDIO = 48000
FS_CTRL_DEFAULT = 32000
CV_SMOOTH_HZ = 2000.0        # the RC on each DAC output
SERVO_HP_HZ = 3.0            # module output DC servo corner

TUNING_HZ = [82.41, 110.00, 146.83, 196.00, 246.94, 329.63]   # E2 A2 D3 G3 B3 E4
# per-string decay, dB/s, tuned against a real picked electric (see karplus_strong)
DECAY_DB_S = [0.9, 1.0, 1.1, 1.2, 1.3, 1.5]
NSTR = 6

PHASE_BITS = 32
PHASE_MOD = 1 << PHASE_BITS


# ============================================================================
# Source material
# ============================================================================

def karplus_strong(f0, dur, fs=FS_AUDIO, decay_db_s=1.0, lp=0.30,
                   pick_pos=0.16, pick_lvl=0.35, seed=0):
    """One plucked string, tuned against a real picked electric.

    The first version of this had no pick transient — it swelled into the note
    and then decayed at a near-constant rate, which made every demo sound more
    organ-like and more forgiving than a real guitar would be. Three fixes:

      * a SHORT excitation burst (2.5 ms) rather than a full delay-line noise
        fill, plus a pick-position comb — this is where the attack comes from
      * a separate bright pick/contact noise transient (~25 ms) added straight
        to the output rather than fed through the loop
      * decay specified in dB/s and converted to a per-trip damping factor, so
        the low strings ring longer than the high ones as they should

    Measured against the target profile for an open picked electric: peak in
    the first 20 ms, 8-12 dB down by 250 ms, then 1.8-3.1 dB/s.
    """
    rng = np.random.default_rng(seed)
    n = int(dur * fs)
    delay = max(2, int(round(fs / f0)))
    damping = 10.0 ** (-decay_db_s / (20.0 * f0))

    burst = min(delay, int(0.0025 * fs))
    ex = np.zeros(delay)
    ex[:burst] = rng.uniform(-1, 1, burst) * np.hanning(burst)
    d = int(pick_pos * delay)
    if d > 0:
        ex[d:] -= ex[:delay - d]

    out = np.zeros(n)
    b = ex.copy()
    idx = 0
    prev = 0.0
    for i in range(n):
        cur = b[idx]
        out[i] = cur
        y = lp * cur + (1.0 - lp) * prev
        prev = cur
        b[idx] = y * damping
        idx = (idx + 1) % delay

    t = np.arange(n) / fs
    nz = rng.uniform(-1, 1, n) * np.exp(-t / 0.025)
    bb, aa = butter(2, [1800 / (fs / 2), 7000 / (fs / 2)], btype="band")
    return out + pick_lvl * lfilter(bb, aa, nz)


def make_stems(dur=21.0, fs=FS_AUDIO, events=None):
    """Six strings, strummed and left to ring. events = [(time, per-string stagger)]."""
    n = int(dur * fs)
    stems = np.zeros((NSTR, n))
    if events is None:
        events = [(0.30, 0.016), (7.00, 0.014), (14.00, 0.018)]
    for ev, (t0, stagger) in enumerate(events):
        for s, f0 in enumerate(TUNING_HZ):
            start = int((t0 + s * stagger) * fs)
            if start >= n:
                continue
            # low strings ring longer than high, as on a real instrument
            decay = DECAY_DB_S[s]
            bright = 0.26 + 0.02 * s
            amp = 0.62 + 0.03 * s
            v = karplus_strong(f0, (n - start) / fs, fs, decay, bright,
                               seed=100 * ev + s)
            stems[s, start:start + len(v)] += amp * v
    return stems


def sustained_stems(dur=16.0, fs=FS_AUDIO):
    """Six sustaining strings — ebow, sustainer pickup, or controlled feedback.

    The reference records this feature evokes all depend on a source that does
    not decay. A plucked chord is gone in four seconds and the texture dies with
    it, so this asks the separate question: does the idea need sustain?
    """
    n = int(dur * fs)
    t = np.arange(n) / fs
    rng = np.random.default_rng(7)
    stems = np.zeros((NSTR, n))
    for s, f0 in enumerate(TUNING_HZ):
        sig = np.zeros(n)
        for h in range(1, 9):
            # slow independent drift per partial: bowed, not additive-synth-static
            amp = (1.0 / h ** 1.35) * (1.0 + 0.35 * np.sin(2 * np.pi * (0.07 + 0.031 * h + 0.013 * s) * t
                                                           + rng.uniform(0, 6.28)))
            sig += amp * np.sin(2 * np.pi * f0 * h * t + rng.uniform(0, 6.28))
        onset = 1.0 - np.exp(-t / (0.6 + 0.15 * s))          # gentle swell in
        stems[s] = 0.22 * sig * onset
    return stems


def load_stems(path):
    fs, data = wavfile.read(path)
    if data.ndim != 2 or data.shape[1] < NSTR:
        raise SystemExit(f"{path}: need a >=6-channel WAV, got shape {data.shape}")
    x = data[:, :NSTR].astype(np.float64).T
    if np.issubdtype(data.dtype, np.integer):
        x /= float(np.iinfo(data.dtype).max)
    if fs != FS_AUDIO:
        print(f"  note: stems are {fs} Hz; rendering at {fs} Hz")
    return x, fs


# ============================================================================
# Shape tables — the firmware's wavetables
# ============================================================================

TBL = 1024
_t = np.arange(TBL) / TBL

SHAPES = {
    # all normalised to [0,1], where 1 = full attenuation by `depth`
    "sine":    0.5 - 0.5 * np.cos(2 * np.pi * _t),
    "tri":     1.0 - np.abs(2 * _t - 1.0) * 1.0,
    "ramp_dn": _t.copy(),
    "ramp_up": 1.0 - _t,
    "pluck":   np.exp(-6.0 * _t),
    "square":  (_t < 0.5).astype(float),
}


def pulse_table(width):
    """Narrow pulse — the shape that makes an auto-strum out of an LFO."""
    return (_t < width).astype(float)


def gate_table(open_frac):
    """1 = open for the first `open_frac` of the cycle, then shut.

    With a small per-string phase offset this is the auto-strum: strings
    re-open in sequence and stay open, which is what a pick does.
    """
    return (_t < open_frac).astype(float)


# ============================================================================
# The engine
# ============================================================================

class Modulator:
    """
    Two modes, both driven by the same 32-bit phase accumulator.

      phase mode : one table, six phase offsets  -> tremolo, rate spread, rake
      row mode   : six tables, one shared phase  -> sequencer, arp, gate masks

    depth_db is applied downward from the calibration, never upward, so the
    pattern never eats headroom at the summing stage.
    """

    def __init__(self, mode, rate_hz, depth_db,
                 table=None, rows=None, spread_deg=0.0, phase0_deg=0.0,
                 interpolate=True, invert=False):
        self.mode = mode
        self.rate_hz = rate_hz
        self.depth_db = depth_db
        self.table = table if table is not None else SHAPES["sine"]
        self.rows = rows
        self.spread = int(round(spread_deg / 360.0 * PHASE_MOD)) % PHASE_MOD
        self.phase = int(round(phase0_deg / 360.0 * PHASE_MOD)) % PHASE_MOD
        self.interpolate = interpolate
        self.invert = invert
        self.inc = 0
        self.only = None                      # None = all strings

    def prepare(self, fs_ctrl):
        self.inc = int(round(self.rate_hz * PHASE_MOD / fs_ctrl)) % PHASE_MOD

    def _lookup(self, ph):
        """ph: 32-bit phase -> table value, with optional linear interpolation."""
        pos = ph * TBL / PHASE_MOD
        i0 = np.floor(pos).astype(np.int64) % TBL
        if not self.interpolate:
            return self.table[i0]
        frac = pos - np.floor(pos)
        i1 = (i0 + 1) % TBL
        return self.table[i0] * (1 - frac) + self.table[i1] * frac

    def render(self, nframes, fs_ctrl):
        """Returns (NSTR, nframes) of dB to SUBTRACT from the calibration."""
        self.prepare(fs_ctrl)
        k = np.arange(nframes, dtype=np.int64)
        base = (self.phase + self.inc * k) % PHASE_MOD
        out = np.zeros((NSTR, nframes))
        if self.mode == "phase":
            for n in range(NSTR):
                ph = (base + n * self.spread) % PHASE_MOD
                v = self._lookup(ph)
                out[n] = self.depth_db * (1.0 - v if self.invert else v)
        elif self.mode == "row":
            nsteps = self.rows.shape[1]
            step = (base * nsteps // PHASE_MOD).astype(np.int64) % nsteps
            for n in range(NSTR):
                gain01 = self.rows[n][step]          # 1 = open, 0 = shut
                out[n] = self.depth_db * (1.0 - gain01)
        elif self.mode == "poly":
            # Polymeter: one shared step clock, but each row loops at its own
            # length. rate_hz is now STEPS per second, not cycles per second.
            # Six coprime lengths take lcm(...) steps to repeat.
            count = (k * self.rate_hz / fs_ctrl).astype(np.int64)
            for n in range(NSTR):
                row = self.rows[n]
                gain01 = row[count % len(row)]
                out[n] = self.depth_db * (1.0 - gain01)
        else:
            raise ValueError(self.mode)
        if self.only is not None:
            keep = np.zeros_like(out)
            keep[self.only] = out[self.only]
            out = keep
        return out


def one_pole(x, fc, fs, axis=-1):
    a = np.exp(-2 * np.pi * fc / fs)
    y = np.empty_like(x)
    if x.ndim == 1:
        acc = x[0]
        for i in range(len(x)):
            acc = (1 - a) * x[i] + a * acc
            y[i] = acc
        return y
    for r in range(x.shape[0]):
        acc = x[r, 0]
        for i in range(x.shape[1]):
            acc = (1 - a) * x[r, i] + a * acc
            y[r, i] = acc
    return y


def envelope_follower(stems, fs_audio, fs_ctrl, atk_ms=3.0, rel_ms=120.0):
    """Rectify at audio rate, peak-decimate to control rate, then attack/release.

    Models the hardware: precision rectifier + RC into an ADC channel, with the
    attack/release done in software at the control frame rate.
    """
    step = int(round(fs_audio / fs_ctrl))
    rect = np.abs(stems)
    nfr = rect.shape[1] // step
    trimmed = rect[:, :nfr * step].reshape(NSTR, nfr, step)
    peak = trimmed.max(axis=2)
    a_atk = np.exp(-1.0 / (atk_ms * 1e-3 * fs_ctrl))
    a_rel = np.exp(-1.0 / (rel_ms * 1e-3 * fs_ctrl))
    env = np.zeros_like(peak)
    acc = np.zeros(NSTR)
    for i in range(nfr):
        x = peak[:, i]
        up = x > acc
        acc = np.where(up, a_atk * acc + (1 - a_atk) * x,
                       a_rel * acc + (1 - a_rel) * x)
        env[:, i] = acc
    return env


def sensing_terms(env, fs_ctrl, gate=None, swell=None):
    """Closed-loop dB terms. Returns (NSTR, nframes) of dB to SUBTRACT."""
    nfr = env.shape[1]
    out = np.zeros((NSTR, nfr))

    if gate is not None:
        thr, depth, hyst, smooth_ms = gate
        st = np.zeros(NSTR, dtype=bool)
        raw = np.zeros((NSTR, nfr))
        for i in range(nfr):
            x = env[:, i]
            st = np.where(st, x > thr * hyst, x > thr)
            raw[:, i] = np.where(st, 0.0, depth)
        out += one_pole(raw, 1000.0 / (2 * np.pi * smooth_ms), fs_ctrl)

    if swell is not None:
        thr, rise_ms, depth = swell
        rise = max(1, int(rise_ms * 1e-3 * fs_ctrl))
        ramp = np.linspace(depth, 0.0, rise)
        raw = np.zeros((NSTR, nfr))
        for n in range(NSTR):
            prev = 0.0
            i = 0
            while i < nfr:
                if env[n, i] > thr and prev <= thr:
                    seg = min(rise, nfr - i)
                    raw[n, i:i + seg] = ramp[:seg]
                    if i + seg < nfr:
                        raw[n, i + seg:] = 0.0
                    prev = env[n, i]
                    i += 1
                    continue
                prev = env[n, i]
                i += 1
        out += raw
    return out


def run(stems, mods, fs_audio=FS_AUDIO, fs_ctrl=FS_CTRL_DEFAULT,
        calib_db=None, gate=None, swell=None,
        crosstalk_db=None, feedthrough_db=None, feedthrough_match=0.3, slew_ms=None,
        cv_smooth_hz=CV_SMOOTH_HZ, floor_db=-60.0):
    """
    Render the mono sum.

      calib_db      : pattern 0, per string, dB (the static balance)
      crosstalk_db  : on-die leakage between channels, or None for ideal
      feedthrough_db: control-feedthrough artefact level, or None for ideal
    """
    nsamp = stems.shape[1]
    step = int(round(fs_audio / fs_ctrl))
    nfr = nsamp // step

    if calib_db is None:
        calib_db = np.zeros(NSTR)

    # --- control domain: decibels add ---------------------------------------
    db = np.tile(np.asarray(calib_db, float)[:, None], (1, nfr))
    for m in mods:
        db -= m.render(nfr, fs_ctrl)

    if gate is not None or swell is not None:
        env = envelope_follower(stems, fs_audio, fs_ctrl)
        env = env[:, :nfr]
        db -= sensing_terms(env, fs_ctrl, gate=gate, swell=swell)

    # Gate-edge slew, in the control domain. A musical control (hard trance
    # edge vs liquid) that doubles as the mitigation for control feedthrough,
    # since feedthrough artefacts scale with dCV/dt.
    if slew_ms:
        db = one_pole(db, 1000.0 / (2 * np.pi * slew_ms), fs_ctrl)

    db = np.clip(db, floor_db, 6.0)

    # --- control voltage: what the DAC actually emits ------------------------
    # SSI2164 law. Positive CV = attenuation. Offset so 0 dB sits 10 dB up.
    MV_PER_DB = -33.0e-3
    cv = (db - 10.0) * MV_PER_DB          # volts at the VCA control pin

    # zero-order hold to audio rate, then the RC on the DAC output
    cv_a = np.repeat(cv, step, axis=1)[:, :nfr * step]
    cv_a = one_pole(cv_a, cv_smooth_hz, fs_audio)
    g = 10.0 ** (((cv_a / MV_PER_DB) + 10.0) / 20.0)

    x = stems[:, :nfr * step]

    # --- audio domain --------------------------------------------------------
    y = g * x
    if crosstalk_db is not None:
        # leakage around each gain element, pre-gain, from the other five
        xt = 10.0 ** (crosstalk_db / 20.0)
        total = x.sum(axis=0)
        y = y + xt * (total[None, :] - x)
    out = y.sum(axis=0)

    if feedthrough_db is not None:
        # CV steps appear as DC at each channel's output; the servo turns them
        # into thumps. The SIX artefacts then sum at the mixer's virtual earth
        # — so a pattern whose total CV is constant cancels its own feedthrough,
        # to the extent that the six channels' feedthrough coefficients match.
        # feedthrough_match: per-channel spread, 0.0 = perfectly matched (an
        # unphysical best case), 0.3 = +-30%, which is realistic for one die.
        ff = 10.0 ** (feedthrough_db / 20.0)
        mism = 1.0 + feedthrough_match * np.array(
            [-1.0, 0.62, -0.31, 0.87, -0.74, 0.56])[:, None]
        cvn = cv_a / 0.033 / 100.0                    # normalise ~full range to 1
        art = cvn - one_pole(cvn, SERVO_HP_HZ, fs_audio)
        out = out + ff * (mism * art).sum(axis=0)

    return out


# ============================================================================
# Patterns used by the demos
# ============================================================================

class PerString(Modulator):
    """A modulator that drives exactly one string. Six of these with slightly
    different rates is feature 2 (rate spread); with audio-rate rates it is
    feature 9 (per-string AM)."""

    def __init__(self, n, rate_hz, depth_db, table=None, phase0_deg=0.0):
        super().__init__("phase", rate_hz, depth_db,
                         table=table if table is not None else SHAPES["sine"],
                         phase0_deg=phase0_deg)
        self.only = n


def rows_arpeggio():
    """16-step Travis-ish pattern. rows[string][step], 1 = open."""
    p = np.zeros((NSTR, 16))
    order = [0, 3, 1, 4, 2, 5, 3, 4, 0, 4, 1, 5, 2, 4, 3, 5]
    for s, n in enumerate(order):
        p[n, s] = 1.0
    return p


def rows_trance_gate():
    p = np.zeros((NSTR, 16))
    patt = {
        0: [0, 4, 8, 12],
        1: [2, 6, 10, 14],
        2: [0, 3, 6, 9, 12],
        3: [4, 12],
        4: [1, 5, 9, 13],
        5: [7, 15],
    }
    for n, steps in patt.items():
        for s in steps:
            p[n, s] = 1.0
    return p


def rows_poly():
    """Six rows, six coprime-ish loop lengths, one shared step clock.

    Lengths 5,7,4,3,8,6 -> lcm = 840 steps before the pattern repeats. At 8
    steps/s that is 105 seconds. This is the churn the reference records have,
    and in the engine it costs one modulo per string.
    """
    lengths = [5, 7, 4, 3, 8, 6]
    hits = [[0, 3], [0, 2, 5], [1], [0], [2, 5, 7], [0, 4]]
    return [np.array([1.0 if i in h else 0.0 for i in range(L)])
            for L, h in zip(lengths, hits)]


def rows_reverse(rows):
    return rows[:, ::-1].copy()


def rows_rotate(rows, by):
    """Rotate which STRING plays each step, keeping the rhythm identical."""
    return np.roll(rows, by, axis=0)


def rows_mask(open_strings):
    p = np.zeros((NSTR, 1))
    for n in open_strings:
        p[n, 0] = 1.0
    return p


# ============================================================================
# Rendering
# ============================================================================

def norm(x, peak=0.89):
    m = np.max(np.abs(x))
    return x * (peak / m) if m > 0 else x


def save(path, x, fs=FS_AUDIO, normalise=True):
    y = norm(x) if normalise else np.clip(x, -1, 1)
    wavfile.write(path, fs, (y * 32767).astype(np.int16))
    print(f"  wrote {os.path.basename(path)}  ({len(y)/fs:.1f}s)")


def concat(*parts):
    return np.concatenate(parts)


def bank_arp(o, stems, ring, fs, args):
    """Variations on sequenced gating — the feature that looks like the lead."""
    ARP = rows_arpeggio()

    def arp_mod(steps_per_sec, depth=40.0, rows=ARP):
        return Modulator("row", rate_hz=steps_per_sec / rows.shape[1],
                         depth_db=depth, rows=rows)

    # A1 — tempo. The features bank runs at 16 steps/s (240 BPM in 16ths).
    #      Here it is at the tempo the variable name claimed.
    segs = [run(ring, [arp_mod(sps)], fs_audio=fs)
            for sps in (8.0, 16.0)]
    save(o("A1-tempo-8-vs-16.wav"), concat(*segs))

    # A2 — rate sweep: where rhythm stops and timbre starts
    segs = [norm(run(ring[:, : int(3.0 * fs)], [arp_mod(sps)], fs_audio=fs))
            for sps in (4.0, 8.0, 16.0, 32.0, 64.0)]
    save(o("A2-rate-sweep.wav"), concat(*segs), normalise=False)

    # A3 — polymeter. Six loop lengths, one clock. 840 steps to repeat.
    poly = Modulator("poly", rate_hz=8.0, depth_db=40.0, rows=rows_poly())
    save(o("A3-polymeter.wav"), run(ring, [poly], fs_audio=fs))

    # A4 — depth. The five shut strings ARE the drone bed; how much do you want?
    segs = [norm(run(ring[:, : int(3.5 * fs)], [arp_mod(16.0, depth=d)], fs_audio=fs))
            for d in (12.0, 26.0, 40.0)]
    save(o("A4-depth-12-26-40.wav"), concat(*segs), normalise=False)

    # A5 — edge slew. Hard trance edge -> liquid. Also the feedthrough mitigation.
    segs = [norm(run(ring[:, : int(3.5 * fs)], [arp_mod(16.0)],
                     fs_audio=fs, slew_ms=sl))
            for sl in (None, 8.0, 30.0)]
    save(o("A5-edge-slew.wav"), concat(*segs), normalise=False)

    # A6 — same rhythm, rotated string assignment, then reversed
    variants = [ARP, rows_rotate(ARP, 2), rows_rotate(ARP, 4), rows_reverse(ARP)]
    segs = [norm(run(ring[:, : int(3.0 * fs)], [arp_mod(16.0, rows=v)], fs_audio=fs))
            for v in variants]
    save(o("A6-rotate-reverse.wav"), concat(*segs), normalise=False)

    # A7 — the real question: does it need sustain?
    sus = sustained_stems(dur=16.0, fs=fs) if not args.stems else stems
    save(o("A7-sustained-dry.wav"), sus.sum(axis=0))
    save(o("A7-sustained-poly.wav"),
         run(sus, [Modulator("poly", rate_hz=8.0, depth_db=40.0, rows=rows_poly())],
             fs_audio=fs))
    save(o("A8-sustained-fast.wav"),
         run(sus, [arp_mod(32.0)], fs_audio=fs, slew_ms=4.0))

    print(f"\ndone -> {args.out}/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stems", help="6-channel WAV off the Nexus; omit to synthesise")
    ap.add_argument("--out", default="demos")
    ap.add_argument("--bank", default="features", choices=("features", "arp"),
                    help="'features' = one demo per feature; "
                         "'arp' = variations on sequenced gating")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    fs = FS_AUDIO
    if args.stems:
        print(f"loading {args.stems}")
        stems, fs = load_stems(args.stems)
    else:
        print("synthesising six strings (Karplus-Strong)")
        stems = make_stems()

    o = lambda name: os.path.join(args.out, name)
    ring = stems[:, : int(7.0 * fs)]          # first strum, left ringing
    long_ring = stems[:, : int(20.0 * fs)]    # three strums, for slow drift

    if args.bank == "arp":
        return bank_arp(o, stems, ring, fs, args)

    # 00 — reference
    save(o("00-dry.wav"), stems.sum(axis=0))

    # 01 — feature 1: tremolo, four spreads, 3.5 s each
    segs = []
    for spread in (0, 60, 120, 180):
        m = Modulator("phase", rate_hz=5.0, depth_db=14.0,
                      table=SHAPES["sine"], spread_deg=spread)
        segs.append(run(ring[:, : int(3.5 * fs)], [m], fs_audio=fs))
    save(o("01-tremolo-spread.wav"), concat(*segs))

    # 02 — feature 2: rate spread. Six near-identical rates drifting apart.
    mods = [PerString(n, 5.0 + 0.09 * n, 13.0) for n in range(NSTR)]
    save(o("02-rate-spread.wav"), run(long_ring, mods, fs_audio=fs))

    # 03 — feature 3: auto-strum / rake. Strings re-open in sequence and stay
    # open — a step shape with a small phase offset, not a pulse.
    #   sweep across 6 strings = 5 * spread/360 / rate  seconds
    rake = Modulator("phase", rate_hz=2.0, depth_db=42.0,          # 50 ms sweep
                     table=gate_table(0.88), spread_deg=7.2, invert=True)
    harp = Modulator("phase", rate_hz=1.0, depth_db=42.0,          # 300 ms sweep
                     table=gate_table(0.75), spread_deg=21.6, invert=True)
    save(o("03-autostrum.wav"),
         concat(run(ring[:, : int(3.5 * fs)], [rake], fs_audio=fs),
                run(ring[:, : int(3.5 * fs)], [harp], fs_audio=fs)))

    # 04 — feature 5: arpeggiator from a held chord
    arp = Modulator("row", rate_hz=120.0 / 60.0 / 2.0, depth_db=40.0,
                    rows=rows_arpeggio())
    save(o("04-arpeggio.wav"), run(ring, [arp], fs_audio=fs))

    # 05 — feature 4: hex trance gate
    tg = Modulator("row", rate_hz=124.0 / 60.0 / 2.0, depth_db=45.0,
                   rows=rows_trance_gate())
    save(o("05-hexgate.wav"), run(ring, [tg], fs_audio=fs))

    # 06 — feature 10: per-string envelope swell (closed loop).
    # A deliberately slow strum, so the six independent blooms are audible.
    slow_strum = (make_stems(dur=14.0, fs=fs, events=[(0.30, 0.25), (7.50, 0.25)])
                  if not args.stems else stems)
    save(o("06-swells-dry.wav"), slow_strum.sum(axis=0))
    save(o("06-swells.wav"),
         run(slow_strum, [], fs_audio=fs, swell=(0.02, 400.0, 45.0)))

    # 07 — feature 6: mute mask switching (chord inversions without moving)
    masks = [[0, 1, 2, 3, 4, 5], [0, 2, 4], [1, 3, 5], [2, 3, 4, 5]]
    segs = []
    for mk in masks:
        m = Modulator("row", rate_hz=0.0001, depth_db=45.0, rows=rows_mask(mk))
        segs.append(run(ring[:, : int(1.7 * fs)], [m], fs_audio=fs))
    save(o("07-mute-masks.wav"), concat(*segs))

    # 08 — RISK: crosstalk sets the gate-depth ceiling
    segs = []
    for xt in (None, -60.0, -46.0):
        tg = Modulator("row", rate_hz=124.0 / 60.0 / 2.0, depth_db=45.0,
                       rows=rows_trance_gate())
        segs.append(norm(run(ring[:, : int(4.0 * fs)], [tg],
                             fs_audio=fs, crosstalk_db=xt)))
    save(o("08-risk-crosstalk.wav"), concat(*segs), normalise=False)

    # 09 — RISK: control feedthrough, heard with NO audio input
    silence = np.zeros_like(ring)
    sq = Modulator("phase", rate_hz=8.0, depth_db=45.0, table=SHAPES["square"])
    segs = []
    for ff in (-72.0, -60.0, -48.0):
        segs.append(run(silence[:, : int(2.5 * fs)], [sq],
                        fs_audio=fs, feedthrough_db=ff))
    quiet = concat(*segs)
    save(o("09-risk-feedthrough.wav"), quiet * 60.0, normalise=False)

    # 10 — feature 9: per-string AM above 20 Hz. Each string gets its own
    # carrier, so each gets its own sideband pair. This is the feature that
    # actually requires a continuous control port and the control bandwidth;
    # no stepped attenuator can do it.
    carriers = [41.0, 53.0, 67.0, 79.0, 97.0, 113.0]
    am = [PerString(n, carriers[n], 9.0) for n in range(NSTR)]
    save(o("10-perstring-am.wav"), run(ring, am, fs_audio=fs))

    print(f"\ndone -> {args.out}/")


if __name__ == "__main__":
    main()