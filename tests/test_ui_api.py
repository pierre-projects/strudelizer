"""The web UI's API (strudelizer_ui), including the errors it reports.

Skipped unless the [ui] extra is installed, like the optional importers.
"""

import json

import pytest

pytest.importorskip("fastapi", reason='the UI extra is not installed (pip install -e ".[ui]")')

from fastapi.testclient import TestClient  # noqa: E402

from strudelizer.core.ir import Song  # noqa: E402
from strudelizer_ui.app import create_app  # noqa: E402

from conftest import FIXTURES, SHEETS  # noqa: E402

MIDI = FIXTURES / "multitrack_repeats.mid"
SHEET = SHEETS / "night_train.txt"


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture(scope="module")
def plugins(client):
    response = client.get("/api/plugins")
    assert response.status_code == 200
    return response.json()


def post_import(client, path, **fields):
    data = {"options": json.dumps(fields.pop("options", {})), **fields}
    with open(path, "rb") as handle:
        response = client.post("/api/import", files={"file": (path.name, handle.read())}, data=data)
    return response


def imported(client, path, **fields):
    response = post_import(client, path, **fields)
    assert response.status_code == 200, response.text
    return response.json()


def error(response, status=400):
    assert response.status_code == status, response.text
    return response.json()["error"]


# ---- /api/plugins -----------------------------------------------------------


def test_plugins_lists_every_registry_group(plugins):
    names = {kind: {p["name"] for p in plugins[kind]} for kind in
             ("importers", "passes", "emitters", "profiles", "styles")}
    assert {"midi", "chordsheet"} <= names["importers"]
    assert {"quantize", "dedupe_bars", "arrange", "transpose"} <= names["passes"]
    assert {"strudel", "midi", "ir_json"} <= names["emitters"]
    assert {"default", "lofi", "techno"} <= names["profiles"]
    assert {"lofi", "rock", "four_on_floor"} <= names["styles"]
    assert plugins["default_passes"] == [
        {"name": "quantize", "options": {"grid": "16+8t"}},
        {"name": "dedupe_bars", "options": {}},
    ]


def test_plugins_describes_options_so_the_panel_can_draw_them(plugins):
    quantize = next(p for p in plugins["passes"] if p["name"] == "quantize")
    grid = next(o for o in quantize["options"] if o["name"] == "grid")
    assert grid["type"] == "select" and grid["default"] == "16+8t"
    assert "16+8t" in grid["choices"] and grid["label"] and grid["help"]

    strudel = next(e for e in plugins["emitters"] if e["name"] == "strudel")
    profile = next(o for o in strudel["options"] if o["name"] == "profile")
    assert profile["choices_from"] == "profiles"

    # A pass with no options says so with [], which is not the same as unknown.
    dedupe = next(p for p in plugins["passes"] if p["name"] == "dedupe_bars")
    assert dedupe["options"] == [] and dedupe["custom"] is False


def test_plugins_labels_every_plugin_for_the_panel(plugins):
    # Every entry carries a label, so the frontend needs no list of plugin names.
    for kind in ("importers", "passes", "emitters", "profiles", "styles"):
        assert all(p["label"] for p in plugins[kind]), kind
    labels = {p["name"]: p["label"] for p in plugins["passes"]}
    assert labels["quantize"] == "Tidy up the timing"
    # A plugin nobody describes falls back to its registered name.
    assert {p["label"] for p in plugins["styles"]} == {s["name"] for s in plugins["styles"]}


def test_plugins_reports_file_types_and_emitter_formats(plugins):
    assert {".mid", ".midi"} <= set(plugins["accept"])
    formats = {e["name"]: e["format"] for e in plugins["emitters"]}
    assert formats["strudel"] == "js" and formats["midi"] == "mid"
    # The Save panel offers this one first, and edited code goes to it.
    assert plugins["default_emitter"] == "strudel"


# ---- /api/import ------------------------------------------------------------


def test_import_detects_the_importer_from_an_uploaded_file(client):
    body = imported(client, MIDI)
    assert body["importer"] == "midi"
    assert body["warnings"] == []
    song = Song.from_dict(body["ir"])  # valid IR, and the source is the user's name
    assert song.meta.source == "multitrack_repeats.mid"
    assert [t.role for t in song.tracks] == ["drums", "bass", "chords", "melody"]


def test_import_reads_pasted_text_and_reports_unparsed_lines(client):
    response = client.post(
        "/api/import",
        data={"text": SHEET.read_text(encoding="utf-8"), "filename": SHEET.name,
              "options": json.dumps({"bpm": 90})},
    )
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["importer"] == "chordsheet"
    assert Song.from_dict(body["ir"]).meta.bpm == 90
    unparsed = [w for w in body["warnings"] if "unparsed" in w["message"]]
    assert unparsed and unparsed[0]["line"] == 16  # clickable in the Problems panel
    assert unparsed[0]["text"].startswith("warning [import:chordsheet]: line 16:")


def test_import_honours_an_importer_override(client):
    # .txt is read by both chordsheet and ascii_tab; the dropdown decides.
    body = imported(client, SHEET, importer="chordsheet", options={"bpm": 90})
    assert body["importer"] == "chordsheet"


def test_import_empty_options_are_dropped_rather_than_passed_on(client):
    # A cleared control posts "", which must mean "use the default", not Fraction("").
    body = imported(client, MIDI, options={"pickup": "", "bpm": None})
    assert Song.from_dict(body["ir"]).meta.pickup_beats is None


def test_import_without_a_file_or_text_says_what_to_do(client):
    detail = error(client.post("/api/import", data={"options": "{}"}))
    assert detail["stage"] == "ui" and detail["message"] == "nothing to import"
    assert "paste" in detail["fix"]


def test_import_of_an_unknown_extension_lists_the_importers(client, tmp_path):
    unknown = tmp_path / "song.zzz"
    unknown.write_bytes(b"nothing readable")
    detail = error(post_import(client, unknown))
    assert detail["stage"] == "import"
    assert detail["location"] == "song.zzz"  # not the temporary copy's path
    assert "midi (.mid, .midi)" in detail["fix"]


def test_import_of_a_corrupt_file_names_the_stage(client, tmp_path):
    broken = tmp_path / "broken.mid"
    broken.write_bytes(b"not a MIDI file at all")
    detail = error(post_import(client, broken))
    assert detail["stage"].startswith("import")
    assert detail["text"].startswith("error [import")


def test_import_with_an_unknown_importer_name(client):
    detail = error(post_import(client, MIDI, importer="nope"))
    assert detail["stage"] == "registry" and "no importer named 'nope'" in detail["message"]


def test_import_rejects_options_that_are_not_a_json_object(client):
    files = {"file": (MIDI.name, MIDI.read_bytes())}
    detail = error(client.post("/api/import", files=files, data={"options": "[1,2]"}))
    assert detail["message"] == "options must be a JSON object"
    detail = error(client.post("/api/import", files=files, data={"options": "{oops"}))
    assert detail["message"].startswith("options is not valid JSON")


# ---- /api/convert -----------------------------------------------------------


def test_convert_returns_code_the_processed_ir_and_warnings(client, plugins):
    ir = imported(client, MIDI)["ir"]
    response = client.post(
        "/api/convert", json={"ir": ir, "passes": plugins["default_passes"], "profile": "lofi"}
    )
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["code"].startswith("// Repeats\n// Source: multitrack_repeats.mid")
    assert "(profile: lofi)" in body["code"] and "LinnDrum" in body["code"]
    # dedupe_bars ran, so the processed IR carries the bar map the emitter used.
    assert any(track.get("bars") for track in body["ir"]["tracks"])
    assert body["warnings"] == []


def test_convert_matches_the_cli_for_the_same_fixture(client, plugins):
    """The UI must not be a second implementation: same input, same bytes."""
    ir = imported(client, SHEET, options={"bpm": 90})["ir"]
    passes = [{"name": "arrange", "options": {"style": "rock"}}] + plugins["default_passes"]
    body = client.post("/api/convert", json={"ir": ir, "passes": passes}).json()
    assert body["code"] == (SHEETS / "night_train.rock.js").read_text(encoding="utf-8")


def test_convert_without_passes_leaves_the_ir_alone(client):
    ir = imported(client, MIDI)["ir"]
    body = client.post("/api/convert", json={"ir": ir}).json()
    assert body["ir"] == ir


def test_convert_renders_only_the_tracks_that_are_not_muted(client):
    ir = imported(client, MIDI)["ir"]
    body = client.post("/api/convert", json={"ir": ir, "tracks": ["drums", "bass"]}).json()
    assert "// drums (drums)" in body["code"] and "// bass (bass)" in body["code"]
    assert "// keys (chords)" not in body["code"] and "// lead (melody)" not in body["code"]
    # The song view still needs every track, so the IR keeps them.
    assert [t["id"] for t in body["ir"]["tracks"]] == ["drums", "bass", "keys", "lead"]


def test_convert_with_every_track_muted_explains_itself(client):
    ir = imported(client, MIDI)["ir"]
    detail = error(client.post("/api/convert", json={"ir": ir, "tracks": []}))
    assert "every track is muted" in detail["message"]


def test_convert_reports_a_bad_pass_option_like_the_cli(client):
    ir = imported(client, MIDI)["ir"]
    detail = error(
        client.post("/api/convert", json={"ir": ir, "passes": [{"name": "quantize", "options": {"grid": "13"}}]})
    )
    assert detail["stage"] == "pass:quantize"
    assert detail["location"] == "option grid='13'"
    assert detail["text"] == (
        "error [pass:quantize] at option grid='13': unknown grid '13'\n"
        "  fix: use 4, 8, 16, 32, 8t or 16t, or combine with +, e.g. quantize:16+8t"
    )


def test_convert_reports_an_unknown_pass(client):
    ir = imported(client, MIDI)["ir"]
    detail = error(client.post("/api/convert", json={"ir": ir, "passes": [{"name": "swingify"}]}))
    assert detail["stage"] == "registry" and "no pass named 'swingify'" in detail["message"]


def test_convert_reports_an_unknown_profile(client):
    ir = imported(client, MIDI)["ir"]
    detail = error(client.post("/api/convert", json={"ir": ir, "profile": "neon"}))
    assert "no profile named 'neon'" in detail["message"]


def test_convert_reports_invalid_ir_against_the_schema(client):
    detail = error(client.post("/api/convert", json={"ir": {"tracks": [{"events": [{"type": "note"}]}]}}))
    assert detail["stage"] == "import:ir"
    assert detail["location"] == "tracks[0].events[0]"
    assert "schema" in detail["message"]


def test_convert_passes_warnings_through(client):
    """A profile that drops a drum warns at emit time; the panel shows it."""
    ir = imported(client, FIXTURES / "pickup_percussion.mid")["ir"]
    body = client.post("/api/convert", json={"ir": ir, "profile": "lofi"}).json()
    assert all(w["stage"] and w["text"].startswith("warning [") for w in body["warnings"])


def test_convert_rejects_a_body_that_is_not_shaped_right(client):
    detail = error(client.post("/api/convert", json={"passes": []}))
    assert detail["stage"] == "ui" and detail["location"] == "ir"


# ---- /api/export ------------------------------------------------------------


@pytest.mark.parametrize(
    "fmt,suffix,media",
    [("js", ".js", "text/javascript"), ("mid", ".mid", "audio/midi"), ("ir.json", ".ir.json", "application/json")],
)
def test_export_writes_each_format(client, fmt, suffix, media):
    ir = imported(client, SHEET, options={"bpm": 90})["ir"]
    response = client.post("/api/export", json={"ir": ir, "format": fmt})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(media)
    assert response.headers["content-disposition"] == f'attachment; filename="night_train{suffix}"'
    assert response.content


def test_export_of_js_matches_the_emitter(client, plugins):
    """Exporting the IR the convert step returned gives the CLI's golden file."""
    ir = imported(client, SHEET, options={"bpm": 90})["ir"]
    processed = client.post("/api/convert", json={"ir": ir, "passes": plugins["default_passes"]}).json()["ir"]
    response = client.post("/api/export", json={"ir": processed, "format": "js"})
    assert response.content.decode("utf-8") == (SHEETS / "night_train.js").read_text(encoding="utf-8")
    techno = client.post("/api/export", json={"ir": processed, "format": "js", "profile": "techno"})
    assert b"(profile: techno)" in techno.content


def test_export_sends_the_edited_code_when_there_is_some(client):
    ir = imported(client, MIDI)["ir"]
    edited = 's("bd sd")  // my own version\n'
    response = client.post("/api/export", json={"ir": ir, "format": "js", "code": edited})
    assert response.content.decode("utf-8") == edited
    # ... but only for Strudel code; the other formats come from the IR.
    response = client.post("/api/export", json={"ir": ir, "format": "mid", "code": edited})
    assert response.content[:4] == b"MThd"


def test_export_of_an_ir_round_trips(client):
    ir = imported(client, MIDI)["ir"]
    response = client.post("/api/export", json={"ir": ir, "format": "ir.json"})
    assert json.loads(response.content) == ir


def test_export_names_the_file_after_the_song(client):
    ir = imported(client, MIDI)["ir"]
    response = client.post("/api/export", json={"ir": ir, "format": "js"})
    assert response.headers["content-disposition"] == 'attachment; filename="repeats.js"'
    response = client.post("/api/export", json={"ir": ir, "format": "js", "filename": "my mix.js"})
    assert response.headers["content-disposition"] == 'attachment; filename="my_mix.js"'
    # The UI sends the name of the file it read, so the suffix is replaced.
    response = client.post("/api/export", json={"ir": ir, "format": "mid", "filename": "Song.mid"})
    assert response.headers["content-disposition"] == 'attachment; filename="song.mid"'
    response = client.post("/api/export", json={"ir": ir, "format": "ir.json", "filename": "song.ir.json"})
    assert response.headers["content-disposition"] == 'attachment; filename="song.ir.json"'


def test_export_of_an_unknown_format_lists_the_known_ones(client):
    ir = imported(client, MIDI)["ir"]
    detail = error(client.post("/api/export", json={"ir": ir, "format": "wav"}))
    assert detail["location"] == "format"
    assert detail["fix"] == "use one of: js, json, mid"


def test_export_validates_the_ir_it_is_given(client):
    detail = error(client.post("/api/export", json={"ir": {"tracks": "none"}, "format": "js"}))
    assert detail["stage"] == "import:ir"


# ---- the page ---------------------------------------------------------------


def test_the_root_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Strudelizer" in response.text
