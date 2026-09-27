"""Built-in pattern library.

Pattern data is transcribed from the Sparta Remix Wiki — "Pitch Patterns"
(https://spartaremix.fandom.com/wiki/Pitch_Patterns), the Chorus, Madness
and Epicness articles — community content under CC BY-SA.  Credits keep the
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

    def parsed(self) -> ParsedPattern:
        if self.lines == "sequence" and "\n" in self.text.strip():
            return parse_sequence(self.text, self.mode)
        return parse(self.text, self.mode)

    def to_dict(self) -> dict:
        d = asdict(self)
        p = self.parsed()
        d["parsed_mode"] = p.mode
        d["steps"] = p.length
        d["bars"] = round(p.length / 16.0, 3)
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
]

MADNESS: list[PatternDef] = [
    P("mad.first", "First Pattern", "madness", "00_00_0011_11_11-2-2_-2-2_-2-211_11_11", mode="compact"),
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

#: The Madness call & response from the Madness article: 1 = first person's
#: word, 2 = the second person answering with the same word.
MADNESS_WORDS: list[PatternDef] = [
    P("madwords.original", "Madness call & response", "madness_words",
      "1***____________2***____________1* 1* 1 1 1'1'1'1'1'/1'/1'/1'/1'/1'/1'/1'/"
      "2* 2* 2 2 2'2'2'2'2'/2'/2'/2'/2'/2'/2'/2'/1***____2***____1* 1 1'1'1'/1'/1'/1'/"
      "2* 2 2'2'2'/2'/2'/2'/1* 11 2* 22 1* 11 2* 22 112211221122 1111", mode="index", credit="Madness"),
]

EPICNESS: list[PatternDef] = [
    # From the Epicness article ("OMG Teh Epicness!").  The wiki text we could
    # reach is incomplete; this is its first four bars, normalised to the bar.
    P("epic.original", "Original (OMG Teh Epicness!)", "epicness",
      "1___1___332_1_1_11__1_1**113_3_2\n1_3_1_332_1_1_111_11111111111111", mode="index", lines="sequence",
      credit="Epicness", fix="partial transcription (4 bars); paste the full Epicness Patterns page to replace it"),
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
                         + MADNESS + MADNESS_WORDS + EPICNESS + FREESTYLES)
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
