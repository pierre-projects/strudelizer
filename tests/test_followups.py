"""P1 follow-ups: boundary-only validation, new drums, pickup bars, IR v2."""

import json
from dataclasses import replace
from fractions import Fraction as F

import mido
import pytest
from conftest import FIXTURES

from strudelizer import Pipeline
from strudelizer.core import Hit, Meta, Note, Song, StrudelizerError, StrudelizerWarning, Track
from strudelizer.core.ir import migrate, validate_dict
from strudelizer.core.time import bar_offset, song_bars, song_length_bars
from strudelizer.emitters.strudel import StrudelEmitter
from strudelizer.importers.midi import MidiImporter
from strudelizer.passes.dedupe_bars import DedupeBars
from strudelizer.passes.quantize import Quantize
from strudelizer.registry import Pass


class BreaksPitch(Pass):
    name = "breaks_pitch"

    def run(self, song, options):
        return replace(song, tracks=song.tracks + (Track(id="x", events=(Note(F(0), F(1), 200),)),))


# ---- validation at boundaries vs --strict ---------------------------------------


def test_non_strict_skips_in_process_validation_strict_catches_it():
    path = FIXTURES / "bassline.mid"
    # in-process pass output is not re-validated outside strict mode
    code = Pipeline(passes=[BreaksPitch()], strict=False).run(path)
    assert "note(" in code
    with pytest.raises(StrudelizerError) as info:
        Pipeline(passes=[BreaksPitch()], strict=True).run(path)
    assert info.value.stage == "pass:breaks_pitch"


def test_ir_leaving_the_process_is_always_validated():
    pipeline = Pipeline(passes=[BreaksPitch()], strict=False)
    song = pipeline.transform(pipeline.load(FIXTURES / "bassline.mid"))
    with pytest.raises(StrudelizerError, match="schema"):
        pipeline.save_ir(song)
    with pytest.raises(StrudelizerError, match="schema"):
        Pipeline(passes=[BreaksPitch()], emitter="ir_json", strict=False).run(FIXTURES / "bassline.mid")


def test_tests_run_strict():
    assert Pipeline().strict is True


def test_cli_strict_flag(tmp_path, capsys):
    from strudelizer.cli import main

    assert main([str(FIXTURES / "bassline.mid"), "--strict", "-o", str(tmp_path / "a.js")]) == 0


# ---- drum vocabulary ---------------------------------------------------------------


def test_new_drums_import_and_play_without_bank():
    song = Pipeline(passes=None).load(FIXTURES / "pickup_percussion.mid")
    drums = {e.drum for t in song.tracks for e in t.events if isinstance(e, Hit)}
    assert {"cowbell", "tambourine", "shaker"} <= drums
    code = StrudelEmitter().emit(song, {})
    banked, unbanked = code.split('.bank("RolandTR909")')
    assert "cb" not in banked and "cb" in unbanked and "sh" in unbanked


def test_bank_with_all_sounds_needs_no_split():
    song = Pipeline(passes=None).load(FIXTURES / "pickup_percussion.mid")
    code = StrudelEmitter().emit(song, {"profile": "lofi"})
    assert code.count(".bank(") == 1


def test_profile_can_drop_a_drum(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("drums: {bank: RolandTR909, map: {cowbell: null}, unbanked: [tambourine, shaker]}\n")
    song = Song(tracks=(Track(id="d", role="drums", events=(Hit(F(0), "cowbell"), Hit(F(1), "kick"))),))
    with pytest.warns(StrudelizerWarning, match="cowbell x1"):
        code = StrudelEmitter().emit(song, {"profile": str(path)})
    assert "cb" not in code and "bd" in code


# ---- pickup bars ------------------------------------------------------------------------


def test_midi_pickup_detected():
    song = MidiImporter().load(FIXTURES / "pickup_percussion.mid", {})
    assert song.meta.pickup_beats == F(1)
    assert song.meta.time_signature == (4, 4)
    assert bar_offset(song.meta) == F(3)
    assert song_length_bars(song) == 3  # pickup bar + 2 full bars


def test_pickup_override_and_bad_pickup(tmp_path):
    song = MidiImporter().load(FIXTURES / "bassline.mid", {"pickup": "2"})
    assert song.meta.pickup_beats == F(2)
    with pytest.raises(StrudelizerError, match="does not fit"):
        MidiImporter().load(FIXTURES / "bassline.mid", {"pickup": "4"})


def test_no_pickup_when_first_meter_is_a_real_bar(tmp_path):
    mid = mido.MidiFile()
    tr = mido.MidiTrack()
    tr.extend([
        mido.MetaMessage("time_signature", numerator=3, denominator=4),
        mido.MetaMessage("time_signature", numerator=2, denominator=4, time=480 * 3),
        mido.Message("note_on", note=60, velocity=90),
        mido.Message("note_off", note=60, time=480),
    ])
    mid.tracks.append(tr)
    path = tmp_path / "m.mid"
    mid.save(str(path))
    with pytest.warns(StrudelizerWarning, match="time signature changes"):
        song = MidiImporter().load(path, {})
    assert song.meta.pickup_beats is None  # 3/4 is longer than the 2/4 that follows


def test_pickup_bar_one_starts_on_cycle_one():
    meta = Meta(time_signature=(4, 4), pickup_beats=F(1))
    song = Song(meta=meta, tracks=(Track(id="m", events=(Note(F(0), F(1), 67), Note(F(1), F(4), 72))),))
    bars = song_bars(song, song.tracks[0].events)
    assert bars[0] == (Note(F(3), F(1), 67),)  # pickup at the end of cycle 0
    assert bars[1] == (Note(F(0), F(4), 72),)  # bar 1 = cycle 1
    code = StrudelEmitter().emit(song, {})
    assert 'note("<[~ ~ ~ g4] c5>")' in code
    assert "// Pickup: 1 beat(s)" in code


def test_quantize_and_dedupe_respect_pickup():
    meta = Meta(time_signature=(4, 4), pickup_beats=F(1, 2))
    events = tuple(Note(F(1, 2) + 4 * b + F(1, 100), F(1), 60) for b in range(3))
    song = Quantize().run(Song(meta=meta, tracks=(Track(events=events),)), {"grid": "4"})
    # grid is aligned to bar lines (offset 7/2), not to the start of the pickup
    assert [e.start for e in song.tracks[0].events] == [F(1, 2), F(9, 2), F(17, 2)]
    assert DedupeBars().run(song, {}).tracks[0].bars == (0, 1, 1, 1)


def test_pickup_must_be_shorter_than_a_bar():
    with pytest.raises(StrudelizerError, match="not shorter than a bar"):
        validate_dict({"meta": {"time_signature": [3, 4], "pickup_beats": "3"}, "tracks": []})


# ---- IR v2 migration ------------------------------------------------------------------------


def test_v1_documents_migrate():
    v1 = json.loads((FIXTURES / "ir" / "sections_chords.ir.json").read_text())
    assert v1["version"] == "1"
    song = Song.from_dict(v1)
    assert song.version == "2"
    assert song.to_dict()["version"] == "2"
    assert migrate({"version": "2", "tracks": []}) == {"version": "2", "tracks": []}


def test_unknown_version_is_a_clear_error():
    with pytest.raises(StrudelizerError, match="unsupported IR version '9'") as info:
        Song.from_dict({"version": "9", "tracks": []})
    assert "upgrade" in info.value.fix
