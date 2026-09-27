"""Built-in pattern library.

Pattern data is transcribed from the Sparta Remix Wiki — "Pitch Patterns"
(https://spartaremix.fandom.com/wiki/Pitch_Patterns), its "Epicness
Patterns" subpage, the Chorus, Madness, Awesomeness and Percussion
articles — community content under CC BY-SA.  Credits keep the
remixer / base names the wiki lists.  Where a transcription does not add up
to whole bars we fixed the obvious typo and say so in ``fix``.

Semitone patterns count from the base's root (0 = D in the classic D bases;
some bases are in D#/Eb, C or A3 and say so in ``key``).  Index patterns
(the standard Chorus, Madness call & response, freestyles) use digits as
sound *slots* — 1 = main pitch / first speaker, 2 = second pitch / second
speaker … — and each hit plays the root of the current chord of the
progression.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from .notation import parse, ParsedPattern, ORIGINAL_PROGRESSION


@dataclass
class PatternDef:
    id: str
    name: str
    section: str
    text: str
    mode: str = "auto"                  # semitone | compact | index | auto
    lines: str = "chord"                # multi-line: "chord" (simultaneous) or "sequence"
    key: Optional[str] = None           # base key when not D
    progression: Optional[str] = ORIGINAL_PROGRESSION  # what it was written over (None: free melody)
    minor: bool = False
    credit: str = ""
    fix: str = ""
    length: Optional[float] = None      # force a loop length in steps
    pickup: float = 0.0                 # steps written before the downbeat (the Epicness "1*" lead-in)
    note: str = ""                      # remarks from the wiki (visual cues, pitch shifts …)

    def parsed(self) -> ParsedPattern:
        if self.lines == "sequence" and "\n" in self.text.strip():
            return parse_sequence(self.text, self.mode)
        return parse(self.text, self.mode)

    def to_dict(self) -> dict:
        d = asdict(self)
        p = self.parsed()
        d["parsed_mode"] = p.mode
        d["steps"] = p.length
        d["bars"] = round((p.length - self.pickup) / 16.0, 3)
        d["voices"] = p.voices
        d["warnings"] = p.warnings
        return d


def parse_sequence(text: str, mode: str = "auto") -> ParsedPattern:
    """Lines played one after another, each padded to a whole bar."""
    from .notation import PNote
    notes: list[PNote] = []
    t = 0.0
    warnings: list[str] = []
    detected = None
    for line in [ln for ln in text.split("\n") if ln.strip()]:
        p = parse(line, mode if mode != "auto" else "auto")
        detected = detected or p.mode
        for n in p.notes:
            notes.append(PNote(n.start + t, n.dur, n.value, 0, n.sharp))
        t += p.padded_length()
        warnings += p.warnings
    return ParsedPattern(notes, t, detected or "semitone", 1, warnings)


P = PatternDef

PROGRESSIONS: list[PatternDef] = [
    P("prog.original", "Original", "progression", "0 1 -2 1"),
    P("prog.e_note", "E Note", "progression", "0 1 2 1"),
    P("prog.e_note_split", "Another E Note pattern", "progression", "0 1 2 1 | -1"),
    P("prog.f_note", "F Note", "progression", "0 1 3 1"),
    P("prog.f_note_split", "Another F Note pattern", "progression", "0 1 3 1 | -1"),
    P("prog.useful", "Useful's style (Tungsten, SparkDox, Cubes V2, …)", "progression", "0 1 3 1 | -2"),
    P("prog.elasticity", "Elasticity", "progression", "0 1 -2 -2 | -1"),
]

INTRO: list[PatternDef] = [
    P("intro.original", "Original", "intro", "-2*** -2*** -2***"),
    P("intro.d_note", "D Note", "intro", "0*** 0*** 0***"),
    P("intro.metro_minor", "Metro/Minor", "intro", "0*** 0*** 0***\n3*** 3*** 3***\n7*** 7*** 7***", minor=True),
    P("intro.nos", "Nos", "intro", "0******3**0**3***0**-2**-4**-2**0*3*", length=32.0,
      fix="adds up to 34 steps with ** = 3; looped at 2 bars"),
    P("intro.interpolation", "Interpolation (A3 Note)", "intro",
      "0*** 0*** 0***\n0*** 0*** 0*** 3***\n0*_3*_7*12*__10*__15*____15*19*__15*__", lines="sequence", key="A3"),
    P("intro.vektor", "Vektor", "intro", "0*****1*****-2*1***0*1***-2***1***"),
]

CHORUS: list[PatternDef] = [
    # The standard Chorus (index notation): three lines played in sequence = 8 bars.
    P("chorus.standard", "Standard Chorus (8 bars)", "chorus",
      "11_11_111_1_1_11222_2_222_222_2_11_11_111_1_1_11222_2_222_222_2_\n"
      "111_1_111_111_1_22_22_222_2_2_22\n"
      "11_11_111_1_1_112'2'2'2'2'2'_2'2'_2'2'2'2'2'2'_2'2'2'2'2'2'_2'2'_",
      mode="index", lines="sequence", credit="Chorus (Main Automation)"),
    P("chorus.standard_a", "Standard Chorus — main line (4 bars)", "chorus",
      "11_11_111_1_1_11222_2_222_222_2_11_11_111_1_1_11222_2_222_222_2_", mode="index"),
    P("chorus.standard_b", "Standard Chorus — swapped line (2 bars)", "chorus",
      "111_1_111_111_1_22_22_222_2_2_22", mode="index"),
    P("chorus.standard_c", "Standard Chorus — 32nd ending (2 bars)", "chorus",
      "11_11_111_1_1_112'2'2'2'2'2'_2'2'_2'2'2'2'2'2'_2'2'2'2'2'2'_2'2'_", mode="index"),
    P("chorus.original", "Original (roots)", "chorus", "0*** 0*** 1*** 1*** -2*** -2*** 1*** 1***"),
    P("chorus.0_12", "0*, 12* pattern", "chorus", "0* 12* 0* 12* 1* 13* 1* 13* -2* 10* -2* 10* 1* 13* 1* 13*"),
    P("chorus.0_7", "0*, 7* pattern", "chorus", "0* 7* 0* 7* 1* 8* 1* 8* -2* 5* -2* 5* 1* 8* 1* 8*"),
    P("chorus.0_4", "0*, 4* pattern", "chorus", "0* 4* 0* 4* 1* 5* 1* 5* -2* 2* -2* 2* 1* 5* 1* 5*"),
    P("chorus.0_m5_m4_1", "0*, -5*, -4*, 1* pattern", "chorus",
      "0* -5* 0* -5* -4* 1* -4* 1* -2* -7* -2* -7* -4* 1* -4* 1*"),
    P("chorus.0_3_minor", "0*, 3* pattern (minor)", "chorus", "0* 3* 0* 3* 1* 5* 1* 5* -2* 1* -2* 1* 1* 5* 1* 5*",
      minor=True),
    P("chorus.0_10_minor", "0*, 10* pattern (minor)", "chorus",
      "0* 10* 0* 10* 1* 12* 1* 12* -2* 8* -2* 8* 1* 12* 1* 12*", minor=True),
    P("chorus.16_0_7", "0, 7 pattern", "chorus",
      "0 0 7 7 0 0 7 7 1 1 8 8 1 1 8 8 -2 -2 5 5 -2 -2 5 5 1 1 8 8 1 1 8 8",
      fix="wiki line is missing one '-2 -2 5 5' group (28 steps)"),
    P("chorus.16_0_4", "0, 4 pattern", "chorus",
      "0 0 4 4 0 0 4 4 1 1 5 5 1 1 5 5 -2 -2 2 2 -2 -2 2 2 1 1 5 5 1 1 5 5"),
    P("chorus.16_0_12", "0, 12 pattern", "chorus",
      "0 0 12 12 0 0 12 12 1 1 13 13 1 1 13 13 -2 -2 10 10 -2 -2 10 10 1 1 13 13 1 1 13 13"),
    P("chorus.16_0_3_minor", "0, 3 pattern (minor)", "chorus",
      "0 0 3 3 0 0 3 3 1 1 5 5 1 1 5 5 -2 -2 1 1 -2 -2 1 1 1 1 5 5 1 1 5 5", minor=True),
    P("chorus.16_0_10_minor", "0, 10 pattern (minor)", "chorus",
      "0 0 10 10 0 0 10 10 1 1 12 12 1 1 12 12 -2 -2 8 8 -2 -2 8 8 1 1 12 12 1 1 12 12", minor=True),
    P("chorus.latin", "Latin (Base)", "chorus", "0* 3* 0* 1*** 5* 1* -2*** -2* 1* 5* 1* 5* 1* 5*", credit="Latin base"),
    P("chorus.tehthaispartan", "TehThaiSpartan", "chorus", "0*** -5*** -4*** 1* 0* -2*** -7*** -4*** 1* -2*"),
    P("chorus.kevin_pfeiffer_uhd", "Kevin Pfeiffer UHD", "chorus", "0*** 3*** 1* 5* 1* 5* -2*** 1*** 5* 1* 5* 1*"),
    P("chorus.blissful_serenity", "Blissful Serenity", "chorus", "-14***-9***-6*-9*-1***-16***-9***-6*-9*-1***"),
    P("chorus.cast", "Cast", "chorus",
      "0/ 3'_ 0/ 3'_ 0'_ 3/ 7/ 3/ 10'_ 7/ 3'_ -2' 2/_ 2/ 5/ 2/ 5/_ -4/ 0/ -4/ 3'_ 0/ -4'_",
      length=32.0, fix="wiki transcription is 35.5 steps; looped at 2 bars"),
    P("chorus.peppermint", "Peppermint", "chorus", "0***__7*5*7*5*4 3 -2*2*5*10*9*4 5 7*5*"),
    P("chorus.interpolation", "Interpolation (Base Is In A3 Note)", "chorus", "0*7*3*12*1*8*5*13*-2*5*1*10*1*8*5*13*",
      key="A3"),
    P("chorus.calypso", "Calypso", "chorus",
      "0'/0'/0*0'/0'/0*1'/1'/1*3'/3'/3*-2'/-2'/-2*-2'/-2'/-2*3'/3'/3*1'/1'/1*"),
    P("chorus.drlasp", "DrLaSp/DrLaSp X (C)", "chorus",
      "-5 -5_0 0_0 0 1_1_1_-4 -4 -2 -2 -2_-2_-2 -2 1_ 1 1 -2_1_", key="C", progression=None),
    P("chorus.fruit", "Fruit", "chorus", "0,0,2,2,-2,-2,2,2", progression=None),
    P("chorus.nemesis", "Nemesis/Nemesis X (D#/Eb)", "chorus",
      "0*_0__0* 1*_1__1* 5'/ 5'/ 5* 10'/ 10'/ 10'/ 10'/ 13* 13'/ 13'/ 13* 13*", key="D#",
      fix="'13/'' read as 13'/"),
]

CHORDS: list[PatternDef] = [
    P("chords.major", "Major", "chords",
      "0****** 1****** -2****** 1******\n4****** 5****** 2****** 5******\n7****** 8****** 5****** 8******"),
    P("chords.minor", "Minor", "chords",
      "0****** 1****** -2****** 1******\n3****** 5****** 1****** 5******\n7****** 8****** 5****** 8******", minor=True),
    P("chords.completely_minor", "Completely Minor", "chords",
      "0****** 1****** -2****** 1******\n3****** 4****** 1****** 4******\n7****** 8****** 5****** 8******", minor=True),
    P("chords.major7", "Major 7ths", "chords",
      "0****** 1****** -2****** 1******\n4****** 5****** 2****** 5******\n7****** 8****** 5****** 8******\n"
      "11****** 12****** 9****** 12******", fix="first 7th written with 5 asterisks on the wiki"),
    P("chords.minor7", "Minor 7ths", "chords",
      "0****** 1****** -2****** 1******\n3****** 5****** 1****** 5******\n7****** 8****** 5****** 8******\n"
      "10****** 12****** 8****** 12******", minor=True, fix="first 7th written with 5 asterisks on the wiki"),
    P("chords.major12", "Major 12ths", "chords",
      "0****** 1****** -2****** 1******\n4****** 5****** 2****** 5******\n7****** 8****** 5****** 8******\n"
      "12****** 13****** 10****** 13******", fix="first 12th written with 5 asterisks on the wiki"),
    P("chords.minor12", "Minor 12ths", "chords",
      "0****** 1****** -2****** 1******\n3****** 5****** 1****** 5******\n7****** 8****** 5****** 8******\n"
      "12****** 13****** 10****** 13******", minor=True, fix="first 12th written with 5 asterisks on the wiki"),
    P("chords.minor_switch", "Minor \"Switch\" (Staircase, Aesthetic, Trinculo, Explotis, Brisk)", "chords",
      "3****** 5****** 1****** 5******\n7****** 8****** 5****** 8******\n10****** 12****** 8****** 12******", minor=True),
    P("chords.aesthetic_alt", "Another alternative for Aesthetic", "chords",
      "3****** 5****** 1****** 5******\n0****** 1****** -2****** 1******\n-4****** -2****** -6****** -2******", minor=True),
    P("chords.tungsten", "Tungsten", "chords",
      "0****** 1****** 3****** 1***-2***\n3****** 5****** 6****** 5*** 2***\n7****** 8****** 10****** 8*** 5***",
      progression=None),
    P("chords.minor_pre_awesomeness2", "Minor Pre-Awesomeness 2 (Cubes V3, Evasteral, Turned, Elasticity V3 …)",
      "chords",
      "3****** 5****** 1****** 5****** 3****** 5****** 10****** 5*** 2***\n"
      "0****** 1****** -2****** 1****** 0****** 1****** 6****** 2*** -1***\n"
      "-4****** -2****** -6****** -2****** -4****** -2****** 3****** -2*** -5***", minor=True, progression=None),
    P("chords.arp_major", "1*, 12*, Chords — Major", "chords",
      "0* 12* 0* 12* 1* 13* 1* 13* -2* 10* -2* 10* 1* 13* 1* 13*\n"
      "4* 16* 4* 16* 5* 17* 5* 17* 2* 14* 2* 14* 5* 17* 5* 17*\n"
      "7* 19* 7* 19* 8* 20* 8* 20* 5* 17* 5* 17* 8* 20* 8* 20*\n"
      "11* 18* 11* 18* 12* 19* 12* 19* 9* 16* 9* 16* 12* 19* 12* 19*", fix="'-2 10*' read as '-2* 10*'"),
    P("chords.arp_minor", "1*, 12*, Chords — Minor", "chords",
      "0* 12* 0* 12* 1* 13* 1* 13* -2* 10* -2* 10* 1* 13* 1* 13*\n"
      "3* 15* 3* 15* 5* 17* 5* 17* 1* 13* 1* 13* 5* 17* 5* 17*\n"
      "7* 19* 7* 19* 8* 20* 8* 20* 5* 17* 5* 17* 8* 20* 8* 20*\n"
      "10* 17* 10* 17* 12* 19* 12* 19* 8* 15* 8* 15* 12* 19* 12* 19*", minor=True,
      fix="the wiki lists only the minor 3rd/7th lines; root and 5th lines taken from the major version"),
]

DUNDUNDENDEN: list[PatternDef] = [
    P("dun.original", "Original", "dundundenden", "0*__0*__1*__1*__-2*__-2*__1*__1*__"),
    P("dun.madhouse_xye", "Madhouse XYE (Fixed by Lyr)", "dundundenden",
      "0* 7* 0* 12* 13* 20* 8* 1* 17* 5* 17* 5* 13* 20* 8* 13*"),
    P("dun.tehotakuspartan", "TehOtakuSpartan", "dundundenden", "0*** 0*** 1*** 8*** -2*** -2*** 3*** 1***",
      fix="'-2***- 2***' read as '-2*** -2***'"),
    P("dun.f1n4l_b34t", "F1N4L B34T", "dundundenden", "12*____12*,13*____13*,10*,10*,10*,10*,13*__12*,13*"),
    P("dun.kaosz", "Kaosz (Base Is In D# Note)", "dundundenden", "0* 7* 4* 7* 1* 8* 5 8 1 8 5* -2* 2 5 10 5 1* 8* 13* 8*",
      key="D#"),
    P("dun.etheral", "Etheral", "dundundenden",
      "-12* -5* -12* 0* 1* -11* -4* -11* -14* -7* -2* -11* 1* -4* 8*** -5* 2* -5* 7* 8* -4* 3* -4* -7* "
      "0* 5* -4* 8* 3* 15*** 0* 7* 0* 12* 13* 1* 8* 1* -2* 5* 10* 1* 13* 8* 20***",
      fix="the three '**' notes read as quarter notes so each chord lasts half a bar (6 bars total)"),
    P("dun.orn", "Orn", "dundundenden", "0*** 0*** 1*** 1* -1* -2*** -2* 1*** 1* -1* 0*"),
    P("dun.lethal", "Lethal", "dundundenden", "-12* -5* -12* 0* 8* 5* 1* 5* 10* 5* 1* -2* 8* 1 5 1* -4*",
      fix="wiki line is 33 steps; '5*' after the 16th read as '5'"),
    P("dun.aduburyus_ae", "Aduburyus AE", "dundundenden", "0* 7* 0* 12* 1***13* 1* 5* -2* 5* 10* 8* 13* 8***"),
    P("dun.dj_cubix", "DJ Cubix Tron Music", "dundundenden", "0* 3* 7 3 2* 1*** 8* 5* 1* -2* 1* 5* 8* 5 8 1* 13*"),
    P("dun.madhouse_jtse_v2", "Madhouse JTSE V2", "dundundenden",
      "0*7*12*7 0 0 7 12 7 0 7 12 7 10*5*-2*0 7 12 7 0 12 7 0 12*"),
    P("dun.jroe", "Jroe", "dundundenden", "0*__0*__1*5*1*8*-2*__-2*__8*5*1*5*", fix="last note read as an 8th (31 steps)"),
    P("dun.nemesis", "Nemesis/Nemesis X (D#/Eb)", "dundundenden",
      "0* 7* 0* 7* 13* 15* 13* 15* 10* 5* 10* 5* 15* 13* 8* 1*", key="D#"),
    P("dun.jyro", "Jyro", "dundundenden",
      "0 4' 7' 12'/7'/4'/7' 0' 4'/7'/1'/8' 5' 8'/ 13'/8'/1' 5' 8'/5'/-2'/2 5'/-2 5' -2' 2'/5'/-2'/1'/8'/5' "
      "8' 13 15* 13*", length=32.0),
]

EXECUTION: list[PatternDef] = [
    P("exec.original", "Original", "execution", "0*_0*_0* 1***__1* -2_-2_-2_-2_1**_1* 1*"),
    P("exec.kingspartax37", "KingSpartaX37", "execution", "0_0_0_0_0_1 -4 -4 _-4_-2_-2_-2_-2_0 -1 1 0 -4_-2"),
    P("exec.pulse", "Pulse (Base, D)", "execution", "0* 7* 0* 12* 13* 8* 13* 1* -2* 5* -2* 10* 13* 8* 13* 1*"),
    P("exec.kaosz", "Kaosz (Base, D#/Eb)", "execution",
      "0* 7* 12* 7* 1 5 8* 13* 8* -2* 5* 10* 5* 1* 8* 13 8 5 1 0* 7* 12* 7* 1 5 8* 13* 8* -2* 5* 10* 5* 1* 8* 13 8 13 20",
      key="D#"),
    P("exec.theepicjwoo2000", "TheEpicJwoo2000", "execution", "0* 0* 0* 0* 0* 1 0 -4* -4* -2* 5* 10* -2* 0 -1 1 0 -4* -2*"),
    P("exec.fap", "FAP (Base)", "execution", "0* 0* 0* 0* 1* 8* 8* 1* 10* 10* 10* 10* 13* 20* 13* 13*"),
    P("exec.hyper_vertex", "Hyper/Vertex (Base)", "execution", "0* 12* 0*** 13*** 1* 13* -2* 10* -2*** 13*** 1* 13*"),
    P("exec.madhouse_otm", "Madhouse OTM (Base)", "execution",
      "0*** 7*** 1* 8 1 8* 1 8 10* 5*__10* 13* 8*__20* 7*** 14*** 8* 15 8 15* 8 15 17* 12* 12* 17* 20* 15* 20* 27*"),
    P("exec.glowchu", "Glowchu", "execution", "0_0_0_0_1_1*__1* -2*______0 -1 1 0 -4_-2"),
    P("exec.daspartanremixer", "DaSpartanRemixer", "execution", "0_0_0_0_1_-4 -4 -4_-2_-2_-2_-2_0_-1 1 0 -4 -2_0"),
    P("exec.latin", "Latin (Base)", "execution",
      "-5* 0* 7*** -4* 1* 8*** 5* 1* 0* -2* 8* 8* 10* 8* 7* 0* -5*** -4* 1* 8*** 5* 1* 0* -2* 8* 8* 10* 8*"),
    P("exec.nemesis", "Nemesis/Nemesis X (Base, D#/Eb)", "execution",
      "8' 8' 8' 8' 8' 8' 8' 8' 8' 8' 8' 8' 8' 8' 8' 8' -5'/ -5'/ -5'/ -5'/ 0' 0' 1' 1' 0' 0' -2' -2' 0'/ 0'/ 0* "
      "6'/ 6'/ 6* 6'/ 6'/ 6* 8___5___", key="D#", length=32.0,
      fix="wiki line is 36 steps; looped at 2 bars"),
    P("exec.tose_v7", "TOSE V7 (Base)", "execution", "0_0_0_0_0_1 0 -4_-4 -3 -2_5 -2_ 5 -2_0 3 8 3 6_5"),
    P("exec.filthy", "Filthy (Base, A3)", "execution",
      "0 0 0 0 7 7 7 7 1 1 1 1 8*** -2* -2* 5* 5* 1* 1* 8*** 0 0 0 0 7 7 7 7 1 1 1 1 8 8 8 8 -2* -2* 5* 5* 1*** 8***",
      key="A3"),
    P("exec.jyro", "Jyro", "execution",
      "0*** 7*** 1*** 5*** -2*** 2*** 1*** 8*** 4*** 7*** 5*** 13*** 2*** 5*** 5*** 8***"),
]

AWESOMENESS: list[PatternDef] = [
    P("awe.1_major", "Awesomeness 1 (Major)", "awesomeness",
      "0_4_12* 24* 1* 5 1 13*** -2_-2_10* 14* 8* 1* 13***0* 7* 12* 16* 17* 5* 1_5 1 -2* 2_29* 10* 1_5 1 20***"),
    P("awe.2_major", "Awesomeness 2 (Major)", "awesomeness",
      "12* 0* 4* 7 4 13* 17* 20* 17* 10* -2* 2* 5* 13* 17* 13* 8* 0* 7* 0 7 12 19 1 8 13 20 13 8 1* -2* 10* 2* 5* "
      "1* 17* 1 5 1 8"),
    P("awe.1_minor", "Awesomeness 1 (Minor)", "awesomeness",
      "0_3_12* 24* 1* 5 1 13*** -2_-2_10* 13* 8* 1* 13***0* 7* 12* 15* 17* 5* 1_5 1 -2* 1_29* 10* 1_5 1 20***",
      minor=True),
    P("awe.2_minor", "Awesomeness 2 (Minor)", "awesomeness",
      "12* 0* 3* 7 3 13* 17* 20* 17* 10* -2* 1* 5* 13* 17* 13* 8* 0* 7* 0 7 12 19 1 8 13 20 13 8 1* -2* 10* 1* 5* "
      "1* 17* 1 5 1 8", minor=True),
    P("awe.1_nemesis", "Awesomeness 1 :: Nemesis/Nemesis X (D#/Eb)", "awesomeness",
      "0_7_12_12 12 8_1_13_8_-2 5 10 5 17 10 17 20__13_20 12_19_24_26_32_25_20_13_10 17 10 17 10_17_20_25_20___",
      key="D#"),
    # ── custom Awesomeness patterns (Awesomeness article) ──
    P("awe.lost_base_1", "Lost base Awesomeness 1", "awesomeness",
      "-5* 2* 7* 14* 8* 3* 8*** -2* 10* 5* -2* 8* 3* 8*** -5* 2* 7* 14* 15* 8* 3* -4* -7* -2* 17* 10* 8* 3* 8***",
      progression=None, credit="Lost base"),
    P("awe.lost_base_2", "Lost base Awesomeness 2", "awesomeness",
      "7* -5* 2* 7* 3* 8* 10* 8* 5* -7* 0* 5* 3* 8* 10* 8* -5* 2* 7* 14* -4* 3* 8* 3* -7* 0* 5* 0 5 8* 3* 8* 15*",
      progression=None, credit="Lost base"),
    P("awe.dreamcloud_1", "DreamCloud's Awesomeness 1", "awesomeness",
      "0* 7* 12* 19* 1* 12 10 13* 13* -2* 17* 10* 5 -2 13* 1* 13* 13* 0* 7* 12* 19* 20* 13* 8* 13 8 -2* 5* 22* 17* "
      "1* 8 1 20* 20*", credit="DreamCloud"),
    P("awe.dreamcloud_2", "DreamCloud's Awesomeness 2", "awesomeness",
      "24* 12* 19* 12* 1* 13* 20* 13*,-2* 17* 10* 5* 1* 8* 13* 20* 0* 7'/19'/7* 12* 1* 8'/20'/13* 25* -2* "
      "17'/5'/10'/17'/17'/10'/1_8 1 25* 32*", credit="DreamCloud"),
    P("awe.jackoy123_1", "Jackoy123's Awesomeness 1", "awesomeness",
      "0* 7* 12* 24* 1* 5 1 13 8 1 13 -2* -2* 10* 14* 8 1* 5 13* 1* 0* 7* 12* 16* 17* 5* 1 13 1 5 -2* 2* 29 24 22* "
      "1* 5 1 20 8 32 32", credit="Jackoy123"),
    P("awe.crash_1", "Crash Awesomeness 1", "awesomeness",
      "0* 4* 7* 12*_12* 13** -2* -2* 10* 13* -4* 12* 13** 0* 4* 12* 16* 17* 12* 5* 0*-2*-2*-2*-2*1*1*1*1*",
      credit="Crash"),
    P("awe.crash_2", "Crash Awesomeness 2", "awesomeness", "12**_12* 13**_13* 10_10_10_10_13**_13*", credit="Crash"),
    P("awe.tomiato64_1", "Tomiato64's Awesomeness 1", "awesomeness",
      "0* 7* 12* 19* 1* 8* 13** -2** 10* 17* 13* 8* 13** 0* 7* 12* 19* 20* 13* 8* 1* -2** 22* 10* 1* 8* 13**",
      credit="Tomiato64"),
    P("awe.tomiato64_2", "Tomiato64's Awesomeness 2", "awesomeness",
      "12* 0* 7* 0* 1* 8* 20* 13* 10* 5* -2* 5* 13* 20* 13* 8* 0 7 12 19 12 19 12* 1 8_13 8 13 8 13 -2* 10* 1* 20* "
      "13* 8*", credit="Tomiato64"),
    P("awe.nemesis_1", "Nemesis Awesomeness 1 (base in D#)", "awesomeness",
      "0_7_12_12 12 8_1_13_1_-2 5 0 10 5 -2 5 8__1_8___0_7_12_14_20_13_8_1_-2 10 -2 5 -2_5_8_13_8___", key="D#",
      credit="Nemesis"),
    P("awe.tgohs_1", "Base TGOHS Edition Awesomeness 1 (GodOfHumand)", "awesomeness",
      "0* 4* 12* 24* 1* 5 1 13*** -2* -2* 10* 14* 8* 1* 13*** 0* 7* 12* 16* 17* 5* 1* 5 1 -2* 2* 29* 10* 1* 5 1 20***",
      credit="GodOfHumand"),
    P("awe.tgohs_2", "Base TGOHS Edition Awesomeness 2 (GodOfHumand)", "awesomeness",
      "12* 0* 4* 7 4 13* 17* 20* 17* 10* -2* 2* 5* 13* 17* 13* 8* 0* 7* 0 7 12 19 1 8 13 20 13 8 1* -2* 10* 2* 5* "
      "1* 17* 13* 1*", credit="GodOfHumand"),
    P("awe.veled_2", "Veled Awesomeness 2 (GodOfHumand)", "awesomeness",
      "12* 0* 4* 7 4 13* 17* 20* 17* 10* -2* 2* 5* 13* 17* 13* 8* 0* 7* 0 7 12 19 1 8 13 20 13 8 1* -2* 10* 2* 5* "
      "1* 17* 13* 8*", credit="GodOfHumand"),
    P("awe.nintendoguy189_1", "dj/nintendoguy189 Awesomeness 1", "awesomeness",
      "0_7_12* 24* 1_8 1 13*** -2_-2_-7* 5 -2 1* -2 8 13*** 0* 7* 12* 19* 20* 13* 20* 25* 22* 17* 10 17 10* 13 20 "
      "13* 20* 32*", credit="dj/nintendoguy189"),
    P("awe.upsilon_1", "Upsilon Awesomeness 1", "awesomeness",
      "0 7 3 10 12* 13 15 17* 15* 13* 15* 10* 13* 12* 10* 5 8 10* 13* 15* 12* 15* 12* 19* 13 10 13* 15* 20* 22 20 17 "
      "13 29* 27* 25 27 25 22 20* 17*", minor=True, credit="Upsilon"),
    P("awe.upsilon_2", "Upsilon Awesomeness 2", "awesomeness",
      "12* 0* 3* 7 12 13* 15* 12* 8 9 10* 13* 15 13 17 20 22* 20* 17* 13 17 19 12 15 7 0 7 12 19 1 8 13 20 13 8 1 8 "
      "10 13 17 13 17* 22* 20* 25* 29 25 29 32", minor=True, credit="Upsilon"),
    P("awe.useful_1", "Useful's Awesomeness 1", "awesomeness",
      "0*_4_12*19 17* 13 17 25*** 10* 10_13*17*8*5 8 1*** 0* 4 0  7* 12 7 13* 17 13 17*13* 22 17 5 -2 2_5 10 13 17 "
      "13*20 13 25* 20*", progression="0 1 3 1 | -2", length=64.0, fix="the wiki line is 66 steps; looped at 4 bars", credit="Useful"),
    P("awe.useful_2", "Useful's Awesomeness 2", "awesomeness",
      "12* 1* 7* 4* 8* 13* 17 20 25* 22* 17_14* 10* 17* 5 8 1*** 0* 4* 0 4 7 12 1 5 8 13 8 5 1* -2 2 5_ -2_ 1* 8 1 "
      "13* 8 13", progression="0 1 3 1 | -2", credit="Useful"),
    P("awe.celeste_1", "Celeste Awesomeness 1", "awesomeness",
      "0* 3 0 12 7 24 19 1 8 5 8 13*** -2* 5 3 5* 10* 8* 1* 13** 8 0 3 0 3 12* 15* 17 16 5* 1* 17* 15* 13* 29* -2* "
      "1* 8 13 20* 25*", minor=True, credit="Celeste"),
    P("awe.celeste_2", "Celeste Awesomeness 2", "awesomeness",
      "12*** 7* 12* 13* 17* 20* 17* 10*__15* 10* 13* 17* 13* 8* 0 3* 12 0 7 12 19 1 8 13 20 13 8 13* -2* 13* 15* "
      "17* 13* 20* 1 17 1 8", credit="Celeste"),
    P("awe.valise_1", "Valise Awesomeness 1", "awesomeness",
      "0* 7* 12* 24* 3_7 3 15***-5_-5_7* 10* 3* -4* 10*** 0* 7* 12* 15* 19* 7* 3* 7 3 -5* -2* 26* 7* -4_0 -4 15***",
      progression=None, credit="Valise"),
    P("awe.tehmondasianspartan", "TehMondasianSpartan Awesomeness", "awesomeness",
      "0_7_12_7 3 13_15_13_15_10_5 8 10_12_13_8 5 13_15_12_7_12_15_17_20_13 8 13_17_10_17_22_20_13_20_13",
      progression=None, credit="TehMondasianSpartan"),
    P("awe.tehmalayspartan", "TehMalay Spartan Awesomeness", "awesomeness",
      "0*-5*0*12*1*-4*1*13*-2*-2*10*14*8*1*13***0*-5*7*12*17***_______17*10*___8***", credit="TehMalay Spartan"),
    P("awe.tungsten_1", "Tungsten Awesomeness 1", "awesomeness",
      "-4*-2*0*3 12*24*1*5 1 13***-2 -2 8 10*13 8 5 1*13***0*3 7*15*17*13*12*13 12 10*5 20*15 13 17 15 13 15 17***15***",
      progression="0 1 3 1 | -2", length=64.0, fix="the wiki line is 67 steps; looped at 4 bars", credit="Tungsten"),
    P("awe.tungsten_2", "Tungsten Awesomeness 2", "awesomeness",
      "0*3_12*24*1*5_1_13***-2_-2_8_10*13_8 5 1*13***0*3_7*15*17*13*12*13_12 15*10 25*20 18 17 15 13 15 14***15***",
      progression="0 1 3 1 | -2", length=64.0, fix="the wiki line is 72 steps; looped at 4 bars", credit="Tungsten"),
    P("awe.tungsten_3", "Tungsten Awesomeness 3", "awesomeness",
      "12*0*3*7_3_13*17*20*14*13*-2*1_5_10*13*8*5 8*7*0*7_0_3_7_8_10_13_8_5_3_1*_-2*_1*5*8*5 8 10 8 12*",
      progression="0 1 3 1 | -2", length=64.0, fix="the wiki line is 77 steps; looped at 4 bars", credit="Tungsten"),
    P("awe.ultimaremixer_1", "UltimaRemixer Awesomeness 1", "awesomeness",
      "0_7_12* 24* 1* 8 1 13*** -2_-2_10* 14* 8* 1* 13***0* 7* 12* 16* 17* 5* 1_5 1 -2* 2_29* 10* 1_1 8 20***",
      credit="UltimaRemixer"),
    P("awe.ultimaremixer_2", "UltimaRemixer Awesomeness 2", "awesomeness",
      "12*______13* 17* 20* 17* 10*______13* 17* 13* 8* 0* 7 0 0 7 12 19 1 8 13 20 13 8 1* -2 -2 10* 5* -2* -11* "
      "17* 13* -11*", credit="UltimaRemixer"),
    P("awe.radical_je", "Radical JE (base in C#)", "awesomeness",
      "12*__0 4 7 4 13* 17* 20* 17* 10*__14 10 5 10 13* 17* 13* 8* 1* 7* 12* 19* 20 17 13 5 1*** -2*** 17* 14* 13 8 "
      "5 8 13***", key="C#", credit="Radical JE"),
    # Not transcribed: XlethYireh's (written as note names without rhythm), Valise 2 and Jario's
    # (written with alternatives in brackets) — see the Awesomeness article.
]

MADNESS: list[PatternDef] = [
    P("mad.first", "First Pattern — Original (from the first half of the Madness until its end)", "madness",
      "00_00_0011_11_11-2-2_-2-2_-2-211_11_11", mode="compact"),
    P("mad.second_half", "Original (from the second half of the Madness; also used for Trance Gates)", "madness",
      "000_000_111_111_-2-2-2_-2-2-2_111_111", mode="compact"),
    P("mad.version", "Version", "madness",
      "0'/00'/0'/00'/0'/0'/1'/11'/1'/11'/1'/1'/-2'/-2-2'/-2'/-2-2'/-2'/-2'/1'/11'/1'/11'/1'/1'/", mode="compact"),
    P("mad.trance_gate", "Second Pattern (aka Trance Gate)", "madness",
      "0'/0'/0*0'/0'/0*1'/1'/1*1'/1'/1*-2'/-2'/-2*-2'/-2'/-2*1'/1'/1*1'/1'/1*"),
    P("mad.variation", "Another Variation", "madness",
      "0'/0*0'/0*0'/0 1'/1*1'/1*1'/1 -2'/-2*-2'/-2*-2'/-2 1'/1*1'/1*1'/1"),
    P("mad.gvt99", "GvT99", "madness",
      "0 0 7 7____2 2 9 9 ____5 5 7 7____3 3 10 10____7 7 2 2 7 7 14 14 2 2 9 9 14 14 9 9 7 7 14 14 7 7 14 14 "
      "2 2 10 10 7 7 10 10", progression=None),
    P("mad.drlasp", "DrLaSp (Note that the base is in C)", "madness",
      "0_12_7_4 3 1_13_8_5 4 -2_10_5_1 -1 1_13_8_5 4", key="C"),
    P("mad.zeta", "Zeta", "madness", "0*_0*_0* 1 8 13 8 1 8 13 8 -2*_-2*_-2* 1 8 13 8 1 8 13 8"),
    P("mad.sonyfive", "SonyFive", "madness", "7* 5' 7' 5 4* 7* 8* 6' 8' 6 5* 8* 5* 3' 5' 3 2* 5* 8* 6' 8' 6 5* 8*",
      mode="semitone", progression=None),
]

#: The Madness call & response (the Madness article, "Chorus Patterns"):
#: 1 = first person's word, 2 = the second person answering with the same
#: (or a similar) word.  All eight bars long.
MADNESS_WORDS: list[PatternDef] = [
    P("madwords.original", "Original Pattern", "madness_words",
      "1*______________2*______________1*______________2*______________"
      "1*______2*______1*______2*______1*__2*__1*__2*__1*__1*__1*__1111\n"
      "________________________________________________________________"
      "________________________________________________2*__2*__2*______",
      mode="index", credit="Madness"),
    P("madwords.tehmontainspartan", "TehMontainSpartan", "madness_words",
      "1***____________2***____________1* 1* 1 1 1'1'1'1'1'/1'/1'/1'/1'/1'/1'/1'/"
      "2* 2* 2 2 2'2'2'2'2'/2'/2'/2'/2'/2'/2'/2'/1***____2***____1* 1 1'1'1'/1'/1'/1'/"
      "2* 2 2'2'2'/2'/2'/2'/1* 11 2* 22 1* 11 2* 22 112211221122 1111", mode="index", credit="TehMontainSpartan",
      note="pitch shift 0 1 2 3 on the last \"1111\""),
    P("madwords.ultraremixer", "UltraRemixer's Pattern (corrected by TehFurrySpartan)", "madness_words",
      "1***____________2***____________1* 1* 1* 11 1'/1'/1'/1'/1'/1'/1'/1'/ 2* 2* 2* 22 2'/2'/2'/2'/2'/2'/2'/2'/"
      "1***____2***____1* 1 1'/1'/1'/1'/1'/ 2* 2 2'/2'/2'/2'/2'/ 1 1 1 1 2 2 2 2 1'1'1'1'1'1'1'1'2'2'2'2'2'2'2'2'"
      "1 1 2 2 1 1 2 2 1 1 2 2 1 1 1 1", mode="index", credit="UltraRemixer"),
    P("madwords.robloxfan75000", "RobloxFan75000 TehMichiganSpartan's Pattern", "madness_words",
      "1***____________2***____________1* 1* 1 1 1'1'1'1'1'/1'/1'/1'/1'/1'/1'/1'/2* 2* 2 2 2'2'2'2'2'/2'/2'/2'/2'/2'/"
      "2'/2'/1***____2***____1* 1 1'1'1'/1'/1'/1'/2* 2 2'2'2'/2'/2'/2'/1'1'1'1'1'1'1'1'2'2'2'2'2'2'2'2'"
      "1''1''1''1''1''1''1''1''1''1''1''1''2''2''2''2''2''2''2''2''2''2''2''2''2''2''2''2''"
      "1'1'1'1'2'2'2'2'1'1'1'1'2'2'2'2'11111111222222221'/1'/1'/1'/", mode="index", length=128.0, credit="RobloxFan75000",
      fix="the wiki's escaped 1\\'\\' read as 64th notes; the line is 139 steps, looped at 8 bars"),
    P("madwords.daspartanremixer", "DaSpartanRemixer", "madness_words",
      "____1*******________2*******____1* 1* 1* 1'1'1'1'1 1'/1'/1'/1'/1'/1'/1'/1'/ 2* 2* 2* 22 "
      "2'/2'/2'/2'/2'/2'/2'/2'/____1*******2*******1*******2*******1***2***1***BBB_B__B__B*BBBB",
      mode="index", length=128.0, fix="the wiki line is 141 steps; looped at 8 bars", credit="DaSpartanRemixer", note="B = 1 and 2 play together"),
    P("madwords.kingspartax37", "KingSpartaX37 (corrected by TehColombianSpartan)", "madness_words",
      "1'1'1'1'1'1'1'1'2_2_3'3'3'3'3'3'3'3'3'/3'/3'3'3'3'4'/4'/4'4'4'/4'/4'/4'4'4'/5***6'6'6'6'6'6'6'6'"
      "1'1'1'1'1'1'1'1'2'/2'/2'/2'/3'3'3'3'3'3'3'3'3'/3'/3'3'3'3'4'/4'/4'4'4'/4'/4'/4'4'4'/5***6'6'6'6'6'6'6'6'"
      "1*1*11112*2*22221*1*11112*2*22221*112*221*112*221122112211221111",
      mode="index", credit="KingSpartaX37", note="pitch shift = +4+4+6+6+4+4+2+2+4/+4/+4+4+4+4"),
]

#: "Pitch Patterns/Epicness Patterns".  Index patterns: 1/2/3 = pitch slots.
#: The leading "1*" is a lead-in before the downbeat (``pickup``), the four
#: bars after it end on a roll of 16ths; the second line layers slot 3.
_EPIC_L2 = "____________________________________________3_3_____3__3_3333_33__"
EPICNESS: list[PatternDef] = [
    # The Epicness as remixers play it on the Chorus's samples: the first hit on the downbeat (not a
    # lead-in), four bars exactly; the second line's 3s fill the gaps before the roll and over it.
    P("epic.downbeat", "Epicness — on the downbeat (the tutorial's version)", "epicness",
      "1_1_332_1_1_11__1_1_113_3_22221_3_1_332_1_1_111_1111111111111111\n"
      + "_" * 39 + "3_3__________3__3_3333_33",
      mode="index", length=64.0,
      credit="as given by the user with therabbit911's Sparta Remix Epicness Tutorial"),
    P("epic.original", "ORIGINAL (OMG Teh Epicness!)", "epicness",
      "1*__1*332*1_1_11__1_1*113_3_22221*3_1*332*1_1_111_1111111111111111\n" + _EPIC_L2,
      mode="index", pickup=2.0, length=64.0, credit="Epicness Patterns"),
    P("epic.theinfyspartan", "@EDIT TheInfySpartan", "epicness",
      "1*__1*332*1_1_11__1_1*113_3_22221*3_1*332*1_1_11__1111111111111111\n" + _EPIC_L2,
      mode="index", pickup=2.0, length=64.0, credit="TheInfySpartan"),
    P("epic.catmanteam_mid2015", "@EDIT CatmanTeam — Mid 2015 (May–August)", "epicness",
      "1*__1*332_2_1_11__1_1*113_3_22221*3_1*33221_1_111_1111111111111111\n" + _EPIC_L2,
      mode="index", pickup=2.0, length=64.0, credit="CatmanTeam"),
    P("epic.catmanteam_late2015", "@EDIT CatmanTeam — Late 2015 (August–November)", "epicness",
      "1*__1*332_2_1_11__1_1*113_3_22221*3_1*332*1_1_111_1111111111111111\n" + _EPIC_L2,
      mode="index", pickup=2.0, length=64.0, credit="CatmanTeam"),
    P("epic.daspartanremixer", "@EDIT DaSpartanRemixer", "epicness",
      "11__11332*1_1_11111_1*113_3_2222113_11332*1_1_111_1111111111111111\n" + _EPIC_L2,
      mode="index", pickup=2.0, length=64.0, credit="DaSpartanRemixer",
      note="the \"1*\" after \"11111_\" is zoomed in and rotated; flipping horizontally starts at the "
           "\"1111111111111111\" roll"),
    P("epic.aq206", "@EDIT AQ206", "epicness",
      "1*1*1*113'3'3'3'3'3'3'3'1*1111**1*1*1*11112/2/2/2/1*3'3'3'3'1*3'3'3'3'1*1*1/1*1*1*1*1*1*_1*_1111111111111111\n"
      "__________________________________________2*_2*_2222_2_22_2222_2",
      mode="index", credit="AQ206", length=80.0, note="pitch shift starts at \"2/2/2/2/\": 0/1/-1/-2/",
      fix="the wiki line is 81.5 steps (\"2/\" read as a 16th + 32nd rest); looped at 5 bars"),
    P("epic.notepadofficial2018", "@EDIT NotepadOfficial2018", "epicness",
      "1_331_332_1_1_11331_1_1133332'2'2'2'2'2'2'2'113311332_1_1_111_"
      "1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'1'\n"
      "____________________________________________3_3_3_3_3_33_33_3333",
      mode="index", credit="NotepadOfficial2018"),
    P("epic.firty_ash", "@EDIT Firty Ash", "epicness",
      "1*__1*332*1_1_11__1_1*113_3_22221*3_1*332*1_1_1_111_1_1_11111111\n"
      "____________________________________________3_3_______3__3_3__3_",
      mode="index", pickup=2.0, length=64.0, credit="Firty Ash"),
    P("epic.floridasr", "@EDIT FloridaSR aka XboxMinion24", "epicness",
      "1*__1*332*2_1-1-11__1_11113_3_22221*3_1*33221-1-1_11__11111111111111\n"
      "________________________________________________3_3_____3__3__333_33",
      mode="index", pickup=2.0, length=64.0, credit="FloridaSR", fix="\"1-\" read as a held 16th"),
    P("epic.thefirealarmspartan_v1", "@EDIT TheFirealarmSpartan — Version 1", "epicness",
      "1*__1'1'1'1'332'2'2'2'1_1_11__1_1'1'1'1'113_3_2'2'2'2'2'2'2'2'1*3_1*332'2'2'2'1_1_111_11111111111111\n"
      "_______________________________________________3_3_____3__3_3333_33",
      mode="index", pickup=2.0, length=64.0, credit="TheFirealarmSpartan"),
    P("epic.thefirealarmspartan_v2", "@EDIT TheFirealarmSpartan — Version 2", "epicness",
      "1_1_1_332/2/2/2/1_1_111_1_1_1113332/2/2/2/2/2/2/2/11_31_332/2/2/2/1_1_111_11111111111111\n"
      "__________________3_3_____3__33333__________________________________3_3_3_3_3_3_3_3_3333",
      mode="index", credit="TheFirealarmSpartan", length=80.0,
      fix="the wiki line is 80 steps (\"2/\" read as a 16th + 32nd rest); looped at 5 bars"),
    P("epic.thekantapapa", "@EDIT TheKantaPapa", "epicness",
      "1*__1*332*1_1_11__1_1*113_3_22221*3_1*332*1_1_111_11111111111111",
      mode="index", pickup=2.0, length=64.0, credit="TheKantaPapa", fix="a lone \"3\" far right of the line is left out"),
    P("epic.tnowa", "@EDIT TNowA", "epicness",
      "1_1_223_1_1_111*1*1_**1**22***3***_1_2_1_22_3_1_2_2______2_2_2_2_",
      mode="index", credit="TNowA", length=64.0,
      fix="stray \"**\" after a rest ignored; the separate \"3_3_11_11_1_13_12121\" line is left out"),
    P("epic.majugarzett", "@EDIT majugarzett", "epicness",
      "1*__1*332*1_1_11__1_1*113_3_22221*3_1*332*1_1_111_1111111111111111\n"
      "____________________________________________3_3_____3__3_3333333__",
      mode="index", pickup=2.0, length=64.0, credit="majugarzett"),
]

FREESTYLES: list[PatternDef] = [
    P("free.glowchu", "Glowchu", "freestyle", "1**1**1**1**1**1**1**22223'3'3'3'3'3'3'3'", mode="index"),
    P("free.jedi_wrong", "Jedi787plus — These Sparta Remixes Are WRONG!!!", "freestyle",
      "11*11*111*1*1*11222*2*222*222*2*11*11*111*1*1*11222*2*222*222*2*", mode="index"),
    P("free.jedi_toda", "Jedi787plus — Toda la vida V2 (four different sounds)", "freestyle",
      "3111_2222_77111_6666_100100_1100_10221022102210_11111_4424111111_", mode="index"),
    P("free.jedi_pc98", "Jedi787plus — PC-98 series", "freestyle",
      "11_11_111_1_1_11222*2*222*222*2*11_11_111_1_1_11222*2*222*222*2*", mode="index"),
    P("free.super_magical", "SUPER MAGICAL FREESTYLE", "freestyle",
      "1111111112223322212233455454332211111111______222222233333211111", mode="index"),
    P("free.g0atfac3", "G0ATFAC3", "freestyle",
      "11_11_111_111_11222_2_222_22222_111_1_111_11111_22_22_222_222_22", mode="index"),
    P("free.veksler96_a", "Veksler96 (A)", "freestyle",
      "12_12_121_2_1_21212_1_212_121_2_12_12_121_2_1_21212_1_212_121_2_", mode="index"),
    P("free.veksler96_b", "Veksler96 (B)", "freestyle",
      "1*_1*_1**_1_1_1*2**_2_2**_2**_2_1*_1*_1**_1_1_1*2**_2_2**_2**_2_", mode="index"),
    P("free.transposed_a", "Transposed 1/2 (A)", "freestyle",
      "111_1_111_111_1_22_22_222_2_2_22111_1_111_111_1_22_22_222_2_2_22", mode="index"),
    P("free.transposed_b", "Transposed 1/2 (B)", "freestyle",
      "11_11_111_1_1_11222_2_222_222_2_111_1_111_111_1_22_22_222_2_2_22", mode="index"),
    P("free.bj_blaskowicz", "B.J Blaskowicz", "freestyle",
      "111122223333222233331*1*1_1_1#1#1#1#1#1#1#1#1*1*1111222233332222", mode="index"),
    P("free.superpikaice", "SuperPikaIce", "freestyle",
      "1*111*111*_1*_1*_1*_22222*__1*_1*_1_1_1111111111112*2222", mode="index"),
    P("free.zozey_1", "Zozey1231 #1 (Sweet 'n' Simple)", "freestyle",
      "1-2__1-2__11111-2__1-2__1_1_1_111-2__1111222233332222333333332_2_2222", mode="index"),
    P("free.zozey_2", "Zozey1231 #2 (Increasing Speed)", "freestyle",
      "1-__1_1_11111===222_2_2_2=2_2_2_11_22_112_2_222211112_223===2_2_", mode="index"),
    P("free.zozey_3", "Zozey1231 #3 (OffBeat)", "freestyle",
      "1-_1-_111-1_1-1111112222333322221-3_1-332===1_1_1111222233332_2_", mode="index"),
    P("free.jackoy_1", "Jackoy123 — first", "freestyle",
      "11_11_11_1111_222_222_222_22222_11_11_111_1111_122_22_222_22222", mode="index"),
    P("free.jackoy_2", "Jackoy123 — second", "freestyle",
      "11_11_111_1111_122_22_222_22222_11_11_111_1111_122_22_222_22222", mode="index"),
    P("free.tracker929", "Tracker929/TehCanadianSpartan", "freestyle",
      "1__2__2_2_2__2_2_2__2_2_444_1*2*2*2*11122444333133__2__22244414__2__2224442_2_2_2__2_2_2_111222444333",
      mode="index"),
    P("free.robloxfan_1", "RobloxFan75000 — first (10.14.18)", "freestyle",
      "1*_1*_1*1111*111_112_223333322221_111_1122223333111112_2233332222", mode="index"),
    P("free.robloxfan_2", "RobloxFan75000 — second (12.09.18)", "freestyle",
      "11*11*1'/1'/1'/1'/1'/1'/1*1_11*11*1_1'/1'/1'/1'/1*1*12321232123212321*1*1'/1'/1'1'1'1'232*4'/4'/4'4'4'4'",
      mode="index"),
    P("free.robloxfan_3", "RobloxFan75000 — third (04.21.19)", "freestyle",
      "123_123_1_1_222211_11112223331_2_1_2_333344444111_2_2_3_3_4'4'4'4'4'4'4'4'", mode="index"),
    P("free.heyltsdan", "HeyltsDanFromCp", "freestyle",
      "1*_1*_1*1*_1*_1*11112222333344441*4_1*4444#4#4#4#4#4#4#4#11111#1#1#1#1#1#1#11114#4#4#4#4#4#4#4#1_1_",
      mode="index"),
    P("free.sonicfans_1", "SonicFans468 — the famous one", "freestyle",
      "1*1*1*1*1*1*11111*1*1*1*11111*1*1122332211223322111111111*1*2222", mode="index"),
    P("free.sonicfans_2", "SonicFans468 — second", "freestyle",
      "1*111*111*1111112222333344441*2*3*444/4/4/4/4/4/4/4/11112/2/2/2/2/2/2/2/2/2/2/33334/4/4/4/4/4/4/4/1*1*",
      mode="index"),
    P("free.toimato64", "Toimato64", "freestyle",
      "11111_1_11111_1_11111_111_1_11111_111_1_3_2_3_2_1_1_33332_223333", mode="index"),
    P("free.godzilla3709", "Godzilla3709", "freestyle",
      "1*2*1*2*1*2*1*2*11112222333344441#1#1#1#2#2#2#2#1#1#1#1#2#2#2#2#1#1#1#1#2#2#2#2#1#1#1#1#2#2#2#2#"
      "1111222233334444", mode="index"),
    P("free.zerubbercat", "ZeRubberCat", "freestyle",
      "11111_2_11111_2_11111_2_1_2_1_2_1*1*1*12*2*2*2*1*1*1*12*2*2*2*1*1*1*12*2*2*21*1*1*12*2*2*2*1_2_1_2_1_11112",
      mode="index"),
    P("free.teh17thspartan", "Teh17thSpartan/~dragonslayer9941~", "freestyle",
      "1*_1*_111*11*_1*11112222333344441_2_1_2_1'1'1'1'1'1'1'1'1'/1'/1'/1'/2_2_22'2'/2'/2'/2'/22222222222",
      mode="index"),
    P("free.super_ultraspartan", "Super UltraSpartan", "freestyle",
      "11*11 111*1 1*11222 2*222 222*2*11*11*111*1*1*11222*2*222*222*2*", mode="index"),
    P("free.roblox_spartan", "Roblox Spartan", "freestyle",
      "1*__1*1*11111'1'1'1'1'1'1'1'1*1_1*1_1*111*1*1111222233332222111111113_3_2222", mode="index"),
    P("free.spartan_dash", "Spartan Dash", "freestyle",
      "1_11_1111_1_1_111_11111_11111'1'1'1'1'1'1'1'11223322112233221'1'1'1'2'2'2'2'3'3'3'3'2'2'2'2'1_11333'3'3'3'",
      mode="index"),
    P("free.handmaster722", "Handmaster722", "freestyle",
      "1*_1*_111*1_1*1*1*1_1*1_1_111*1*1_1*1_11222_33331*111*1122223333", mode="index"),
    P("free.creeper125", "CREEPER 125", "freestyle",
      "1*1_1*1_1*_1*_1*1*1_1*1_1*_1*_1*1*1_1*1_2*2*333_2_223*3_3*_3*_3", mode="index"),
    P("free.gage_1", "GageDaRemixer #1", "freestyle",
      "1_331_332_1131311_113131333322221133113322113_331_11311311313131", mode="index"),
    P("free.gage_3", "GageDaRemixer #3", "freestyle",
      "1_2_3_4_112_3_4_1_3_1_3_112233441_3_1_3_222211114444111122221_1_", mode="index"),
    P("free.raichu", "Raichu the Great", "freestyle", "1*_1*_1*_1_111_1112222_222*33_41_", mode="index"),
    P("free.usf", "USF", "freestyle", "11_11_111_1_1_11222_2_222_222_2_1111_2222_2_1_1_221_1_2222", mode="index"),
    P("free.jastuk55", "Jastuk55", "freestyle",
      "1***1***1***1*1*1***1***11111*1*1111222233332222111111113_3_2222", mode="index"),
    P("free.jvids24", "TheLuigiFan007/JVids24", "freestyle",
      "1*_1*_1*1'1'1'1'1'1'1'1'1*1*1*_1*_1_1*_1*_1*1*_1*_1*1'1'1'1'1'1'1'1'11112'2'2'2'2'2'2'2'11113'3'3'3'3'3'"
      "3'3'1_1", mode="index"),
    P("free.polandball", "TehPolandballSpartan", "freestyle",
      "1_1_222211111_1_1_2_1_2_12121_2_1_1_11111_1_2222112211221_1_2222", mode="index"),
    P("free.notepad2018", "NotepadOfficial2018", "freestyle",
      "11_11_11111_1_11222_2_222_222_22111_1_111_111_1122_22_22222_2_22", mode="index"),
    P("free.classicspartan", "ClassicSpartanOverland1000Spartan", "freestyle",
      "0***0***0***0***0***0***0***0***0*0*0*0*0*0*0*0*1111111112_2333", mode="compact"),
    P("free.caner", "CanerTheSpartan's Chorus-Style", "freestyle",
      "1'1'1'1_1'1'1'1_1'1'1'1'1'1_1'1'_1'1'_1'1'1'1'2'2'2'2'2'2'_2'2'_2'2'2'2'2'2'_2'2'2'2'2'2'_2'2'",
      mode="index"),
]

#: The Percussion article: index patterns where 1 = kick, 2 = clap/snare and
#: 3 = hi-hat (a closed one for repetitive lines, an open one in-pattern).
#: Today the kick is usually paralleled with the snare (see PERC_SLOTS).
PERCUSSION: list[PatternDef] = [
    P("perc.original_2011", "Original 2011-2012 Percussion", "percussion", "1*__2*____1*2*__1*__2*1*__1*2*__",
      mode="index", progression=None),
    P("perc.normal", "Normal Percussion", "percussion",
      "1*__1*__1*__1*__1*__1*__1*__1*__\n__3*__3*__3*__3*__3*__3*__3*__3*\n____2*______2*______2*______2*__",
      mode="index", progression=None),
    P("perc.vitro", "Vitro Percussion", "percussion",
      "1*__1*__1*__1*__1*__1*__1*__1*__\n__3*__3*__3*__3*__3*__3*__3*__3*\n____2*______2*____2*2*22*22*2*2*",
      mode="index", progression=None),
    P("perc.vitro_b", "Vitro Percussion (second)", "percussion",
      "1*__1*__1*__1*__1*1*______1*__1*\n____2*______2*______2*__2*__2*__", mode="index", progression=None),
    P("perc.generic", "Generic Percussion", "percussion", "1*__2*__1*__2*__1*__2*__1*__2*__", mode="index",
      progression=None),
    P("perc.original", "Original Percussion", "percussion",
      "1_332_331_332_331_332_331_332_33\n3_3_3_3_3_3_3_3_3_3_3_3_\n1__2__1__2__1__2__1__2__", mode="index",
      progression=None, length=32.0, fix="the second and third lines are 24 steps; looped at 2 bars"),
    P("perc.sparta_crash_mix", "Sparta Crash Mix", "percussion", "1*__2*__1*1*2*__1*1*2*221*1*2*__", mode="index",
      progression=None),
    P("perc.paystyle", "Paystyle/Antimatter", "percussion", "1*332*331*332*331*332*331*332*33", mode="index",
      progression=None),
    P("perc.sparta_base_mix", "Sparta Base Mix", "percussion", "1*__1*__2*__1*1*__1*1*__2*__1*__", mode="index",
      progression=None),
    P("perc.filthy", "Filthy Base", "percussion",
      "1*__1*__1*1*1*__1*__1*__1*1*1*__\n333_3___3___3_3_333_3___3___3_3_\n____2_______2_______2_______2___",
      mode="index", progression=None),
    P("perc.enraged", "Enraged", "percussion", "1__1__2__11", mode="index", progression=None, length=8.0,
      note="repeat"),
    P("perc.pulse_v7", "Pulse V7", "percussion",
      "1*__2*__1*__2*__1*__2*__1*__2*1*1*__2*__1*__2*__1*__2*__1*__2*11", mode="index", progression=None,
      note="the snare starts at the second Pulse pitch; before that it is kicks only"),
    P("perc.churckrock_cd3", "ChurckRock CD3", "percussion", "1*__2*__1*1*2*__1*__2*1*1*1*2*__", mode="index",
      progression=None),
    P("perc.drlasp", "DrLaSp", "percussion", "1*3_2*3_1*3_2*33", mode="index", progression=None),
    P("perc.officialtheface", "Officialtheface (freestyle)", "percussion",
      "1*_________________________2*_______1*_________________________3*____2", mode="index", progression=None),
    P("perc.gagethegamer", "GageTheGamer (freestyle)", "percussion",
      "1*1*2_1_1*112_1*1*112_1*1*112_22\n1_2_1_2**221_2_1_2**22\n3_3_3_333_333_33", mode="index", progression=None),
    P("perc.zertytv", "ZertyTV (freestyle)", "percussion", "1_1_1_111_1_11", mode="index", progression=None,
      length=16.0),
]

HIHATS: list[PatternDef] = [
    P("hat.16ths", "16th notes", "hihat", "33333333333333333333333333333333", mode="index", progression=None),
    P("hat.16ths_spaced", "16th notes with spaces", "hihat", "3_3_3_3_3_3_3_3_3_3_3_3_3_3_3_3_", mode="index",
      progression=None),
    P("hat.12ths", "12th notes", "hihat", "3*3*3*3*3*3*3*3*3*3*3*3*3*3*3*3*", mode="index", progression=None),
    P("hat.333", "333 pattern", "hihat", "333_____333_____333_____333_____", mode="index", progression=None),
    P("hat.333_v2", "333 pattern 2.0", "hihat", "333_333_333_333_333_333_333_333_", mode="index", progression=None),
]

#: Default sounds for the percussion slots: the kick is paralleled with the
#: snare, closed hats sit well under the kick.
PERC_SLOTS = {
    "1": {"sample": "kick", "visual": "kick"},
    "2": [{"sample": "clap", "visual": "snare"}, {"sample": "kick", "gain": -2.0, "visual": "none"}],
    "3": {"sample": "hat_closed", "gain": -9.0, "visual": "hat"},
}


# ── Rhythm patterns for the source-made percussion and bass (our own) ────────
# These are not pitch patterns from the wiki; they are the backing grooves the
# engine plays with the source's kick / snare / hats when no base is supplied.

DRUMS: dict[str, dict[str, str]] = {
    "four_on_floor": {"kick": "1___1___1___1___", "snare": "____1_______1___",
                      "hat_closed": "__1___1___1___1_", "hat_open": ""},
    "four_on_floor_16": {"kick": "1___1___1___1___", "snare": "____1_______1___",
                         "hat_closed": "1111111111111111", "hat_open": "__1___1___1___1_"},
    "half_time": {"kick": "1_______1_______", "snare": "________1_______", "hat_closed": "1_1_1_1_1_1_1_1_",
                  "hat_open": ""},
    "breakdown": {"kick": "", "snare": "", "hat_closed": "__1___1___1___1_", "hat_open": ""},
    "build": {"kick": "1___1___1___1___", "snare": "1_1_1_1_11111111", "hat_closed": "1111111111111111",
              "hat_open": ""},
}

BASS: dict[str, str] = {
    "offbeat": "__1*__1*__1*__1*",
    "rolling": "_111_111_111_111",
    "eighths": "1*1*1*1*1*1*1*1*",
    "roots": "1***1***1***1***",
    "held": "1******1******",
}

ALL: list[PatternDef] = (PROGRESSIONS + INTRO + CHORUS + CHORDS + DUNDUNDENDEN + EXECUTION + AWESOMENESS
                         + MADNESS + MADNESS_WORDS + EPICNESS + FREESTYLES + PERCUSSION + HIHATS)
BY_ID: dict[str, PatternDef] = {p.id: p for p in ALL}

SECTION_TITLES = {
    "progression": "Progression Twist",
    "intro": "Intro",
    "chorus": "Chorus",
    "chords": "Chords",
    "dundundenden": "DunDunDenDen (Buildup)",
    "execution": "Execution",
    "awesomeness": "Awesomeness",
    "madness": "Madness (pitch)",
    "madness_words": "Madness (call & response)",
    "epicness": "Epicness",
    "freestyle": "Freestyles",
    "percussion": "Percussion (1 kick, 2 clap/snare, 3 hi-hat)",
    "hihat": "Closed hi-hats",
}


def get(pid: str) -> PatternDef:
    try:
        return BY_ID[pid]
    except KeyError as exc:
        raise KeyError(f"unknown pattern id {pid!r}") from exc


def by_section(section: str) -> list[PatternDef]:
    return [p for p in ALL if p.section == section]


def catalog() -> dict:
    return {
        "sections": {s: [p.to_dict() for p in by_section(s)] for s in SECTION_TITLES},
        "titles": SECTION_TITLES,
        "drums": DRUMS,
        "bass": BASS,
    }


def register(defn: PatternDef) -> None:
    """Add a user pattern (e.g. pasted from the wiki) to the live library."""
    if defn.id in BY_ID:
        ALL.remove(BY_ID[defn.id])
    ALL.append(defn)
    BY_ID[defn.id] = defn
