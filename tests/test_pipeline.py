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


def test_pass_spec_keeps_windows_drive_paths():
    """A Windows path's drive colon is not an option separator (this broke
    remap_drums on CI's D: drive, where a drive-relative path missed)."""
    from strudelizer.pipeline import _split_args

    assert _split_args(r"remap_drums:C:\kits\a.yaml") == ["remap_drums", r"C:\kits\a.yaml"]
    assert _split_args("remap_drums:D:/kits/a.yaml") == ["remap_drums", "D:/kits/a.yaml"]
    assert _split_args(r"remap_drums:map=C:\kits\a.yaml") == ["remap_drums", r"map=C:\kits\a.yaml"]
    assert _split_args("quantize:16:grid=8t") == ["quantize", "16", "grid=8t"]
    assert _split_args("arrange:style=/home/me/my.yaml") == ["arrange", "style=/home/me/my.yaml"]
    specs = parse_pass_spec(r"remap_drums:C:\kits\a.yaml,quantize:16")
    assert [(p.name, o) for p, o in specs] == [("remap_drums", {"map": r"C:\kits\a.yaml"}), ("quantize", {"grid": "16"})]


def test_two_bare_arguments_are_an_error():
    with pytest.raises(StrudelizerError, match="one bare argument"):
        parse_pass_spec("quantize:16:8t")
