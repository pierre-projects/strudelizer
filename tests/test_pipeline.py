from dataclasses import replace
from fractions import Fraction as F

import pytest
from conftest import FIXTURES

from strudelizer import Pipeline
from strudelizer.core import Note, StrudelizerError, Track
from strudelizer.pipeline import parse_pass_spec
from strudelizer.registry import Pass


class BreaksPitch(Pass):
    """Test pass that produces an out-of-range pitch."""

    name = "breaks_pitch"

    def run(self, song, options):
        bad = Track(id="x", events=(Note(F(0), F(1), 200),))
        return replace(song, tracks=song.tracks + (bad,))


class ReturnsNothing(Pass):
    name = "returns_nothing"

    def run(self, song, options):
        return None


def test_pass_output_is_validated_and_stage_named():
    with pytest.raises(StrudelizerError) as info:
        Pipeline(passes=[BreaksPitch()]).run(FIXTURES / "bassline.mid")
    assert info.value.stage == "pass:breaks_pitch"
    assert info.value.message.startswith("output song IR does not match the schema")
    assert info.value.location == "tracks[1].events[0].pitch"


def test_pass_must_return_a_song():
    with pytest.raises(StrudelizerError, match="not a Song") as info:
        Pipeline(passes=[ReturnsNothing()]).run(FIXTURES / "bassline.mid")
    assert info.value.stage == "pass:returns_nothing"


def test_parse_pass_spec():
    specs = parse_pass_spec("quantize:16, dedupe_bars,quantize:grid=8t")
    assert [(p.name, o) for p, o in specs] == [
        ("quantize", {"grid": "16"}),
        ("dedupe_bars", {}),
        ("quantize", {"grid": "8t"}),
    ]
    assert parse_pass_spec("") == []
    assert parse_pass_spec(None) == []
    with pytest.raises(StrudelizerError, match="no bare argument"):
        parse_pass_spec("dedupe_bars:3")
    with pytest.raises(StrudelizerError, match="no pass named"):
        parse_pass_spec("nope")


def test_api_with_names_instances_and_tuples():
    from strudelizer.registry import get_pass

    a = Pipeline("midi", [("quantize", {"grid": "16+8t"}), get_pass("dedupe_bars")], "strudel", profile="lofi")
    b = Pipeline(passes="quantize:16+8t,dedupe_bars", profile="lofi")
    path = FIXTURES / "melody_triplets.mid"
    assert a.run(path) == b.run(path)
    assert "(profile: lofi)" in a.run(path)
