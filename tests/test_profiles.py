import pytest

from strudelizer import registry
from strudelizer.core import StrudelizerError
from strudelizer.profiles import DEFAULT_DRUM_MAP


@pytest.mark.parametrize("name", ["default", "lofi", "techno"])
def test_builtin_profiles_load_and_validate(name):
    profile = registry.get_profile(name)
    assert profile["name"] == name
    assert set(profile["drums"]["map"]) == set(DEFAULT_DRUM_MAP)
    assert set(profile["roles"]) == {"bass", "chords", "melody", "vocal", "other"}
    assert profile["drums"]["bank"]


def test_profile_from_path_fills_defaults(tmp_path):
    path = tmp_path / "mine.yaml"
    path.write_text("name: mine\nroles:\n  other: {sound: sine, fx: [{hpf: 200}]}\ndrums: {map: {kick: bd:3}}\n")
    profile = registry.get_profile(str(path))
    assert profile["roles"]["bass"] == {"sound": "sine", "fx": [{"hpf": 200}]}  # falls back to `other`
    assert profile["drums"]["map"]["kick"] == "bd:3"
    assert profile["drums"]["map"]["snare"] == "sd"
    assert profile["drums"]["bank"] is None


@pytest.mark.parametrize(
    "text,where",
    [
        ("roles: {lead: {sound: sine}}", "roles"),
        ("drums: {map: {agogo: ag}}", "drums.map"),
        ("roles: {bass: {fx: [{'bad name': 1}]}}", "roles.bass.fx.0"),
        ("roles: {bass: {sound: 'saw tooth'}}", "roles.bass.sound"),
    ],
)
def test_invalid_profiles_are_rejected(tmp_path, text, where):
    path = tmp_path / "bad.yaml"
    path.write_text(text)
    with pytest.raises(StrudelizerError) as info:
        registry.get_profile(str(path))
    assert info.value.stage == "profile"
    assert where in info.value.location


def test_broken_yaml_reports_line(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("name: x\nroles: [\n")
    with pytest.raises(StrudelizerError, match="not valid YAML") as info:
        registry.get_profile(str(path))
    assert "line" in info.value.location


def test_unknown_profile_name():
    with pytest.raises(StrudelizerError) as info:
        registry.get_profile("nope")
    assert "lofi" in info.value.fix
