# Sparta Gen — a real Sparta Remix generator

Sparta Gen turns any video into a **Sparta Remix** the way remixers build them by hand — no AI music, no synthesizers:

1. **Cuts the source video into samples** with ffmpeg — held vowels/notes become *pitches*, thumps/bangs/hisses become
   *kick, snare/clap, hi-hats and crash*, and speech becomes *quotes*, *Madness words* and *DunDunDenDen syllables*.
2. **Fixes every pitch sample into a D note** (the key of the classic bases) with TD-PSOLA hard-tuning — the
   "Melodyne pitch drift 100 %" treatment — and derives the **bass** (D2), **main**, **second** and **third** pitches.
3. **Sequences the patterns from the Sparta Remix Wiki** (standard Chorus `11_11_111_1_1_11222_2_222_222_2_…`,
   DunDunDenDen, Madness call & response, Epicness, Awesomeness 1/2, Execution, chords, 43 freestyles…) over the
   classic D → E♭ → C → E♭ progression.
4. **Polishes the mix with an Xleth-style FX rack** (3-band OTT, ChorusCrisp "Jario" pluck, compressor, limiter,
   saturation, reverb, delay, chorus, flanger, phaser, transient shaper, sidechain pump, filter sweeps, tape stop).
5. **Renders the video**: every note shows its own clip, in sync — fullscreen hits, Madness split screen, 3×3/4×4
   grids, flips on every hit, flashes, kick zoom-punch and the spinning *OMG TEH EPICNESS* text.

Everything happens in one app with a **preview before you save**, on **Windows, macOS, Linux and Android**.

![Sample detection](docs/gui-samples.jpg)

---

## Contents

- [Install](#install) · [Using the app](#using-the-app) · [Command line](#command-line)
- [Base variants](#base-variants) · [Pattern notation](#pattern-notation) · [How samples are made](#how-samples-are-made)
- [FX polishing](#fx-polishing) · [Using a real Sparta base](#using-a-real-sparta-base) · [Sample pack export](#sample-pack-export)
- [Development](#development) · [Credits](#credits) · [Known limitations](#known-limitations)

## Install

| Platform | Easiest way |
|---|---|
| **Windows / macOS / Linux** | Download `SpartaGen-<os>.zip` (ffmpeg included), unzip, run `SpartaGen` (`SpartaGen.app` on macOS). The zips are built by CI: push a tag like `v0.1.0` (they are attached to the release) or run the *test & build* workflow from the Actions tab (they appear as run artifacts). |
| **From source (any desktop)** | Install Python 3.9+, then double-click `scripts/run_windows.bat`, `scripts/run_macos.command`, or run `scripts/run_unix.sh`. First start creates a virtual environment and installs everything (ffmpeg comes from `imageio-ffmpeg` if you have none). |
| **Android** | Install [Termux](https://termux.dev) (F-Droid/GitHub build), then run `curl -fsSL https://raw.githubusercontent.com/TheQSN/sparta-gen/HEAD/scripts/install-termux.sh \| bash`. Start with `spartagen gui` — the app opens in your phone's browser. Your videos are under `~/storage/shared/`. *Private repository?* In Termux: `pkg install git && git clone https://<token>@github.com/TheQSN/sparta-gen ~/sparta-gen && bash ~/sparta-gen/scripts/install-termux.sh` (a GitHub token with read access). |
| **pip** | `pip install -e ".[all]"` (needs ffmpeg on PATH or the `imageio-ffmpeg` extra), then `spartagen gui`. |

Requirements: **ffmpeg** and **numpy**. `scipy` (faster), `yt-dlp` (links), `pillow` (titles) are optional —
there is a pure-numpy fallback for every filter, so minimal installs (e.g. Termux without scipy) still work.

## Using the app

`spartagen gui` (or the desktop app) starts a local engine and opens the UI in your browser
(`--window` opens a native window when `pywebview` is installed). It works on phone screens too.

1. **Source** — drop a video, paste a YouTube/other link (downloaded with yt-dlp), or give a local path.
   Press **Detect samples**.
2. **Samples** — every detected sample is shown with its clip, time range, detected note and the tuning
   (e.g. `D#5 → D5 (-1.01 st)`). ▶ plays the processed sample, ◇ plays the original cut (and its video).
   Swap any sample for another candidate, or type a start/end time. Change the key (default **D**), the pitch
   octave or how hard the pitch is flattened.
3. **Remix** — pick a base variant, BPM, *Progression Twist* (Original `0 1 -2 1`, E Note, F Note, Useful's,
   Elasticity…), pitching and polish level. Every section and track is editable: pick any wiki pattern from the
   library (with a piano-roll preview), type your own in wiki notation, change gain/octave/bars, mute tracks,
   reorder/duplicate/add sections (Intro, Chorus, DunDunDenDen, Epicness, Awesomeness, Madness, Execution…).
   The **Pattern lab** parses anything you paste from the wiki and can add it to the library.
4. **Preview & Save** — **Render preview** makes a fast 640×360 version to watch first; **Render final video**
   renders 720p/1080p. Download the MP4 and WAV, export the **sample pack**, save the project.

![Arrangement editor](docs/gui-remix.jpg)

<p align="center"><img src="docs/gui-phone.jpg" width="420" alt="Phone layout"></p>

## Command line

```bash
spartagen make  video.mp4 --variant semi_extended --quality 720p -o remix.mp4
spartagen make  "https://www.youtube.com/watch?v=…" --variant extended --pack pack/   # also export the sample pack
spartagen make  video.mp4 --audio-only -o remix.wav --polish hard --progression "0 1 3 1 | -2"
spartagen make  video.mp4 --base my_sparta_base.mp3 --base-offset 0.42               # remix on top of a real base
spartagen analyze video.mp4              # what would be cut into samples (pitches with their notes, hits, quotes)
spartagen pack    video.mp4 -o pack/     # tuned samples as WAV + their video clips as MP4
spartagen patterns --section chorus      # the pattern library
spartagen patterns --parse "11_11_111_1_1_11222_2_222_222_2_"
spartagen variants
```

Useful options: `--bpm`, `--key D`, `--pitch-octave 4`, `--pitching classic|normal|hard`,
`--polish light|normal|hard`, `--minor`, `--chorus-pattern chorus.0_12`, `--intro-pattern intro.nos`,
`--stems`, `--project project.json`.

## Base variants

| Variant | BPM | Length | Structure |
|---|---|---|---|
| **Unextended** | 140 | 43 bars ≈ 1:14 | Intro · intro hits · Chorus · DunDunDenDen · Chorus · Madness · final Chorus · Ending |
| **Semi-Extended** | 140 | 55 bars ≈ 1:34 | + Epicness and Awesomeness 1 — **hard pitching** (octave, chord and arp layers) and **hard FX polishing** (heavy OTT, sidechain pump) |
| **Extended** | 140 | 75 bars ≈ 2:09 | 8-bar DunDunDenDen, Epicness after the 2nd Chorus and after the Madness, Awesomeness 1 before the Madness, Awesomeness 2 opening the final Chorus |
| **Hyper** | 160 | 55 bars ≈ 1:23 | Semi-extended with the Hyper/Vertex execution pattern, hard pitching and FX |
| **Minor** | 140 | 67 bars ≈ 1:55 | Extended with the wiki's minor variants (Metro/Minor intro, minor chords, `0*, 3*` arps, minor Awesomeness) |
| **Classic (2010)** | 140 | 43 bars ≈ 1:14 | Unextended with sampler ("chipmunk") pitching, no OTT, light polish |

Sections and what plays in them:

- **Chorus** — the standard 8-bar Chorus (3 lines: main line ×2, swapped line, 32nd-note ending); `1` = main pitch,
  `2` = second pitch, each hit on the root of the current chord; ChorusCrisp pluck; offbeat bass; four-on-the-floor
  source kick, clap paralleled with the kick, hats; crash; fill in the last bar. Grid 3×3 visuals.
- **DunDunDenDen** — `0*__0*__1*__1*__-2*__-2*__1*__1*__`: loud quarter notes with silence in between, each hit a
  syllable of the **main phrase** pitched to the note, all drums hitting with it. Fullscreen, black between hits.
- **Madness** — the call & response (`1` = first person's word, `2` = second person repeating it, with the 32nd rolls)
  over the softer, low-passed Madness pitch patterns (First Pattern, then Trance Gate). Split screen.
- **Epicness** — the "OMG Teh Epicness!" pattern with chords and arps. 4×4 grid with the spinning title.
- **Awesomeness 1 / 2**, **Execution**, **Intro** (quotes, then the 3-hit intro pattern), **Ending** (final hit,
  main phrase, tape stop).

## Pattern notation

Patterns use the Sparta Remix Wiki notation (*Pitch Patterns* page):

| Symbol | Meaning | Symbol | Meaning |
|---|---|---|---|
| `***` | 4th note | `0` (bare number) | 16th note |
| `**` | "6th" note (3 sixteenths) | `'` | 32nd note |
| `*` | 8th note | `"` | 64th note |
| `+#` / `-#` | # semitones up / down | `_` | 16th rest |
| `#` | root key/note (`0`) | `/` · `\` | 32nd · 64th rest |
| `\|` | semi-progression (split) | `*****` · `******` | dotted quarter · half note |

Three styles are recognised automatically (you can also force one):

- **semitone** — `0* 12* 0* 12* 1* 13* …`: numbers are semitones from the base's root (0 = D).
- **compact** — `00_00_0011_11_11-2-2_…` (Madness *First Pattern*): each digit is its own note.
- **index** — `11_11_111_1_1_11222_2_…` (standard Chorus, Madness): digits are **slots** — 1 = main pitch / first
  speaker, 2 = second pitch / second speaker… — and each hit plays the root of the current chord.

Picking a **Progression Twist** re-targets every semitone pattern written for `0 1 -2 1` (e.g. under `0 1 2 1` a
note on C moves to E). Multi-line patterns (Chords) play their lines together.

The library holds **139 patterns** from the wiki (7 progressions, 6 intros, 27 chorus patterns, 13 chord sets,
14 DunDunDenDens, 15 Execution patterns, 5 Awesomeness, 7 Madness + the call & response, Epicness, 43 freestyles).
Where a wiki transcription did not add up to whole bars, the obvious typo is fixed and documented in the source
(`spartagen/patterns/library.py`, field `fix`).

## How samples are made

- **Detection** (`spartagen/audio/analysis.py`): frame features at ~11.6 ms (energy, band energies, band-limited
  spectral flatness, spectral flux, MFCCs) plus a vectorised YIN pitch tracker.
  - *Pitch* candidates are steady voiced windows (local pitch spread < 35 cents), ranked by length, stability,
    clarity, loudness and "vowel-ness". Pitch 2 and 3 come from other moments of the source (another word or
    speaker) so the Chorus call & response is audible.
  - *Kick* = sharp onsets with low-frequency body; *snare/clap* = sharp, noisy, broadband "bangs";
    *hats* = sibilants ("s", "ts") and cymbal hiss; *crash* = longer loud noisy stretches.
  - *Quotes* are phrases between pauses; *words* are split at energy valleys; the best quote is the
    **main phrase**, chopped into syllables for the DunDunDenDen.
- **Tuning to D** (`spartagen/audio/psola.py`): pitch marks every period, TD-PSOLA re-synthesis with every period at
  the target note (formants kept). Transpositions reuse the synthesis marks; long notes are sustained by PSOLA
  stretching or ping-pong looping of the steady part.
- **Designed hits** (`spartagen/samples.py`): kick = the thump pitched down for body + pitch-sweep punch + the
  original click; snare/clap = EQ'd bang with transient boost (clap = three retriggers); hats = high-passed hiss with
  short/long decays; crash = noise + long reverb tail; bass = the lowest tuned pitch dropped to D2, low-passed and
  saturated.

Every sample keeps its source time range, so its **video clip is known** — that is what the renderer shows.

## FX polishing

Modelled on the effects [Xleth](https://github.com/composition-cassidy/Xleth) ships for Sparta/YTPMV work
(independent numpy implementations, no Xleth code is included):
**OTT** (3-band Linkwitz-Riley split, upward + downward compression with the classic OTT band table; depth scales
compression, not a dry/wet mix), compressor, look-ahead limiter, EQ/filters, waveshaper (tanh/soft/hard/fold/asym),
transient processor, bitcrusher, algorithmic reverb, ping-pong delay, chorus, flanger, phaser, stereo width,
kick-driven sidechain pump, trance gate, filter sweeps, tape stop, stutter and pitch sweeps — plus the
**ChorusCrisp** "Jario Style" pluck on chorus notes (split at 40 ms, 80 % overlap, −3 dB duck).
Masters land around −12 / −10 / −8.5 LUFS for light / normal / hard polish with a −1 dBFS ceiling.

![Rendered frames](docs/remix-frames.jpg)

## Using a real Sparta base

Remixes normally sit on a Sparta base. In the *Remix* tab (or `--base`), add a base and set where bar 1 starts.
In *replace* mode the app mutes its own source-made drums, bass and pads and lays the pitches, chops, quotes and
Madness words on top of the base; *layer* keeps everything.

## Sample pack export

*Export sample pack* (or `spartagen pack`) writes every sample as a WAV (pitches already tuned to D) **and** its
video clip as an MP4 with the processed audio, plus `samples.json` — ready for Vegas, FL Studio or Xleth if you
prefer to finish by hand.

## Development

```bash
pip install -e ".[dev]"
pytest                 # 130 tests: notation, DSP, pitch accuracy, full pipeline, HTTP API
python scripts/build_desktop.py   # PyInstaller build with ffmpeg bundled (what CI does per OS)
```

Layout: `spartagen/ffmpeg.py` (media I/O) · `audio/` (dsp, pitch, psola, analysis, fx) · `samples.py` ·
`patterns/` (notation parser, wiki library) · `arrangement.py` (variants, sections, note compiler) ·
`render_audio.py` · `render_video.py` · `project.py` (pipeline) · `cli.py` · `gui/` (server + static UI).
CI (`.github/workflows/build.yml`) runs the tests with and without scipy on every push and builds the desktop apps
for tags (`v*`) or on manual dispatch.

## Credits

- Pattern data: [Sparta Remix Wiki](https://spartaremix.fandom.com/wiki/Pitch_Patterns) contributors
  (CC BY-SA) — remixer and base names are kept with each pattern.
- Design references: [Xleth](https://github.com/composition-cassidy/Xleth) (FX set, OTT behaviour, declick,
  PSOLA/loop ideas), [ChorusCrisp](https://github.com/composition-cassidy/ChorusCrisp) (the Jario pluck),
  [Sparta Remix Visual Editor](https://github.com/composition-cassidy/Sparta-Remix-Visual-Editor) (grid/flip
  conventions) by composition-cassidy.
- YIN: de Cheveigné & Kawahara (2002). BS.1770-4 loudness. TD-PSOLA: Moulines & Charpentier (1990).

## Known limitations

- Detection is signal-based: on busy sources (music under dialogue) the automatic picks can be imperfect — swap
  candidates or type a time range in the *Samples* tab.
- The *Epicness* pattern shipped is a partial transcription; paste the wiki's *Pitch Patterns/Epicness Patterns*
  into the Pattern lab to use the full ones. Where the wiki places the *Execution* section varies by base — it is
  available as a section to add (the Hyper variant uses it).
- Some Chromium builds without proprietary codecs cannot play H.264 in the page; the app then offers the preview
  as a download (normal Chrome, Edge, Firefox, Safari and Android browsers play it).
- Android runs through Termux (no store APK yet).
