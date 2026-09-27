import numpy as np
import pytest

from spartagen.audio import dsp, fx, psola
from spartagen.audio.pitch import cents_deviation, hz_to_midi, midi_to_hz, yin_track

from conftest import SR, harmonic_tone


def median_f0(x):
    tr = yin_track(x, SR, hop=256)
    v = tr.f0[tr.voiced]
    v = v[len(v) // 6: len(v) - len(v) // 6]
    return float(np.median(v)), cents_deviation(v)


@pytest.mark.parametrize("f0", [82.4, 146.83, 220.0, 440.0])
def test_yin_is_accurate(f0):
    x = harmonic_tone(f0, 0.8)
    got, _ = median_f0(x)
    assert abs(1200 * np.log2(got / f0)) < 3.0


def test_yin_rejects_noise():
    x = (np.random.RandomState(0).randn(SR) * 0.3).astype(np.float32)
    assert yin_track(x, SR).voiced.mean() < 0.05


def test_psola_hard_tunes_to_d_and_flattens_vibrato():
    x = harmonic_tone(180.0, 0.6, vibrato_cents=30.0)
    ts = psola.tune_to_note(x, SR, midi_to_hz(50))          # D3
    got, dev = median_f0(ts.audio)
    assert abs(1200 * np.log2(got / midi_to_hz(50))) < 5.0
    assert dev < 5.0
    assert ts.audio.shape == x.shape


@pytest.mark.parametrize("semis", [-12, -2, 1, 7, 12])
def test_psola_shift_hits_the_interval(semis):
    ts = psola.tune_to_note(harmonic_tone(150.0, 0.6), SR, midi_to_hz(50))
    got, _ = median_f0(psola.shift(ts, semis))
    want = midi_to_hz(50 + semis)
    assert abs(1200 * np.log2(got / want)) < 10.0


def test_psola_sustain_stretch_keeps_pitch():
    ts = psola.tune_to_note(harmonic_tone(150.0, 0.3), SR, midi_to_hz(50))
    y = psola.shift(ts, 0, out_len=int(1.2 * SR))
    assert y.shape[0] == int(1.2 * SR)
    got, _ = median_f0(y)
    assert abs(1200 * np.log2(got / midi_to_hz(50))) < 10.0


def test_resample_and_varispeed():
    x = np.sin(2 * np.pi * 440 * np.arange(SR) / SR).astype(np.float32)
    assert dsp.resample_ratio(x, 2.0).shape[0] == 2 * SR
    y = dsp.varispeed(x, 12)
    assert abs(y.shape[0] - SR // 2) <= 1


def test_filters_match_without_scipy(monkeypatch):
    x = np.random.RandomState(1).randn(SR).astype(np.float32)
    sos = dsp.butter_sos("highpass", 150.0, SR, 4)
    ref = dsp.sosfilt(sos, x, SR)
    monkeypatch.setattr(dsp, "_sps", None)
    alt = dsp.sosfilt(sos, x, SR)
    assert np.max(np.abs(ref - alt)) < 1e-3


def test_loudness_reference():
    t = np.arange(SR * 3) / SR
    x = 0.1 * np.sin(2 * np.pi * 997 * t)
    assert abs(dsp.loudness_lufs(np.stack([x, x], 1), SR) + 20.0) < 0.2


def test_running_max():
    x = np.random.RandomState(3).rand(5000)
    for w in (1, 7, 64):
        ref = np.array([x[i:i + w].max() for i in range(len(x))])
        assert np.allclose(dsp.running_max(x, w), ref)


def test_limiter_respects_ceiling():
    x = (np.random.RandomState(2).randn(SR, 2) * 0.8).astype(np.float32)
    y = fx.limiter(x, SR, ceiling_db=-1.0)
    assert dsp.peak(y) <= dsp.db_to_gain(-1.0) + 1e-6


def test_ott_is_transparent_at_zero_depth():
    x = harmonic_tone(220.0, 1.0)
    y = fx.ott(x, SR, depth=0.0)
    # The LR4 split/recombine is an allpass: same magnitude spectrum, same energy.
    assert abs(dsp.rms(y) - dsp.rms(x)) / dsp.rms(x) < 0.02


@pytest.mark.parametrize("name", ["chorus", "flanger", "phaser", "transient", "saturate", "bitcrush", "reverb", "delay",
                                  "compressor", "tape_stop", "filter_sweep"])
def test_fx_rack_runs(name):
    x = harmonic_tone(220.0, 0.8)
    y = fx.apply_chain(x, SR, [{"fx": name}])
    assert np.all(np.isfinite(y)) and y.shape[0] == x.shape[0]


def test_wav_roundtrip(tmp_path):
    x = (np.random.RandomState(4).rand(1000, 2) * 1.6 - 0.8).astype(np.float32)
    p = str(tmp_path / "a.wav")
    dsp.write_wav(p, x, SR, bits=32)
    y, sr = dsp.read_wav(p)
    assert sr == SR and np.allclose(x, y)


def test_harmonic_filter_keeps_the_voice_and_drops_the_band():
    from conftest import harmonic_tone
    from spartagen.audio.harmonic import harmonic_filter
    sr = 44100
    voice = harmonic_tone(220.0, 0.5, sr)
    t = np.arange(voice.shape[0]) / sr
    band = (0.08 * np.sin(2 * np.pi * 311.1 * t) + 0.08 * np.sin(2 * np.pi * 392.0 * t)).astype(np.float32)
    y, voiced = harmonic_filter(voice + band, sr, f0_hint=220.0)

    def level(sig, f):
        S = np.abs(np.fft.rfft(sig * np.hanning(sig.shape[0])))
        fr = np.fft.rfftfreq(sig.shape[0], 1.0 / sr)
        k = int(np.argmin(np.abs(fr - f)))
        return 20 * np.log10(S[k - 3:k + 4].max() + 1e-9)

    mix = voice + band
    assert level(mix, 220.0) - level(y, 220.0) < 6.0          # the voice stays
    assert level(mix, 311.1) - level(y, 311.1) > 20.0         # the band goes
    assert level(mix, 392.0) - level(y, 392.0) > 20.0
    assert voiced > 0.8
    assert np.corrcoef(y[2000:-2000], voice[2000:-2000])[0, 1] > 0.97


def test_a_hum_keeps_its_level_an_octave_up():
    """A voice with hardly any overtones (a hum) loses its high notes when the formants are kept; the
    quality score sees it and the renderer plays such notes the sampler way instead."""
    from spartagen.audio import psola, dsp as D
    from spartagen.samples import Sample, octave_up_drop_db
    from spartagen.render_audio import VoiceRenderer, MixConfig
    from spartagen.samples import SampleBank
    from tests.conftest import harmonic_tone
    sr = 44100
    t = np.arange(int(0.2 * sr)) / sr
    hum = (0.3 * np.sin(2 * np.pi * 293.66 * t) * np.minimum(1, np.minimum(t / 0.01, (0.2 - t) / 0.02))).astype(np.float32)
    rich = harmonic_tone(293.66, 0.2, sr)
    samples = {}
    for name, x in (("hum", hum), ("rich", rich)):
        ts = psola.tune_to_note(x, sr, 293.66)
        samples[name] = Sample(name, "pitch", name, 0.0, 0.2, ts.audio, sr, 62.0, ts)
    assert octave_up_drop_db(samples["hum"]) > 9.0 > octave_up_drop_db(samples["rich"])
    bank = SampleBank(sr)
    bank.samples.update(samples)
    vr = VoiceRenderer(bank, MixConfig())
    for name in ("hum", "rich"):
        y = vr._shifted(samples[name], 12.0, int(0.2 * sr))
        assert 20 * np.log10(D.rms(samples[name].audio) / D.rms(y)) < 9.0, name


def test_a_pitch_is_cut_to_its_held_note():
    """A sung word = consonant + held vowel + glide away; the pitch sample keeps the held vowel only."""
    from spartagen.samples import steady_core
    from tests.conftest import harmonic_tone, noise_burst
    sr = 44100
    cons = 0.3 * noise_burst(0.04, sr, decay_ms=30.0)
    held = harmonic_tone(293.66, 0.2, sr)
    t = np.arange(int(0.08 * sr)) / sr
    glide = (0.2 * np.sin(2 * np.pi * np.cumsum(293.66 * 2 ** (t / 0.08 * 5 / 12)) / sr)).astype(np.float32)
    x = np.concatenate([cons[: int(0.04 * sr)], held, glide]).astype(np.float32)
    a, b = steady_core(x, sr)
    assert abs(a / sr - 0.04) < 0.02 and abs(b / sr - 0.24) < 0.03
