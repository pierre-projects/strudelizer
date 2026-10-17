from importlib.metadata import EntryPoint

import pytest

from strudelizer import registry
from strudelizer.core import Song, StrudelizerError, Track
from strudelizer.registry import Importer


class FakeTabImporter(Importer):
    """Third-party style importer used only by this test."""

    name = "faketab"
    extensions = (".faketab",)

    def load(self, path, options):
        return Song(tracks=(Track(events=()),))


def _with_extra(monkeypatch, group, *eps):
    real = registry._discover

    def fake(g):
        found = real(g)
        return found + list(eps) if g == group else found

    monkeypatch.setattr(registry, "_discover", fake)


def test_builtins_are_registered_via_entry_points():
    assert [p.name for p in registry.available("importer")] == ["chordsheet", "midi"]
    assert [p.name for p in registry.available("pass")] == [
        "arrange", "dedupe_bars", "detect_sections", "quantize", "remap_drums", "transpose",
    ]
    assert [p.name for p in registry.available("emitter")] == ["ir_json", "midi", "strudel"]
    assert [p.name for p in registry.available("profile")] == ["default", "lofi", "techno"]
    assert [p.name for p in registry.available("style")] == ["four_on_floor", "lofi", "rock"]
    assert all(p.distribution == "strudelizer" for p in registry.available("importer"))


def test_third_party_plugin_is_discovered(monkeypatch, tmp_path):
    ep = EntryPoint("faketab", f"{__name__}:FakeTabImporter", "strudelizer.importers")
    _with_extra(monkeypatch, "strudelizer.importers", ep)
    assert "faketab" in [p.name for p in registry.available("importer")]
    path = tmp_path / "song.faketab"
    path.write_text("x")
    importer = registry.find_importer(path)
    assert isinstance(importer, FakeTabImporter)


def test_duplicate_names_are_rejected(monkeypatch):
    ep = EntryPoint("midi", f"{__name__}:FakeTabImporter", "strudelizer.importers")
    _with_extra(monkeypatch, "strudelizer.importers", ep)
    with pytest.raises(StrudelizerError, match="two importer plugins are named 'midi'"):
        registry.available("importer")


def test_unknown_names_list_alternatives():
    with pytest.raises(StrudelizerError) as info:
        registry.get_emitter("nope")
    assert "ir_json" in info.value.fix and "strudel" in info.value.fix


def test_no_importer_for_file(tmp_path):
    with pytest.raises(StrudelizerError) as info:
        registry.find_importer(tmp_path / "song.xyz")
    assert info.value.stage == "import"
    assert "midi" in info.value.fix
