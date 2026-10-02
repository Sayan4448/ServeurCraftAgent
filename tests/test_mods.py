"""Installation de mods / plugins : pas de doublon, bonne version, clé
CurseForge et erreurs réseau."""
import json

import pytest
import requests

from app import config
from app.core import mods


class Resp:
    def __init__(self, status=200, data=None, text=None):
        self.status_code = status
        self._data = data
        self.ok = 200 <= status < 300
        self.text = text or ""

    def json(self):
        if self._data is None:
            raise ValueError("pas du JSON")
        return self._data

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(response=self)


def _version(number, kind="release", project="P1"):
    return {"version_number": number, "version_type": kind,
            "project_id": project,
            "files": [{"primary": True, "url": f"https://x/{number}",
                       "filename": f"AuthMe-{number}.jar"}]}


@pytest.fixture
def offline_modrinth(monkeypatch):
    """Téléchargements simulés ; Modrinth ne connaît aucun fichier local."""
    def fake_download(url, dest, progress_cb=None):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(url.encode())
        return dest
    monkeypatch.setattr(mods, "download_file", fake_download)
    monkeypatch.setattr(mods, "_identify_modrinth", lambda folder, known: {})


def _jars(server, sub="plugins"):
    return sorted(p.name for p in (server / sub).glob("*.jar"))


# ------------------------------------------------------------- versions

def test_stable_release_preferred_over_newer_beta():
    versions = [_version("7.0-beta", "beta"), _version("6.0.1"),
                _version("5.9")]
    assert mods._best_version(versions)["version_number"] == "6.0.1"


def test_beta_used_when_no_release_exists():
    versions = [_version("7.0-alpha", "alpha"), _version("7.0-beta", "beta")]
    assert mods._best_version(versions)["version_number"] == "7.0-beta"


# -------------------------------------------------------------- doublons

def test_installing_twice_does_not_duplicate(make_server, monkeypatch,
                                             offline_modrinth):
    server = make_server()
    monkeypatch.setattr(mods, "_modrinth_versions",
                        lambda *a: [_version("6.0.1")])
    for _ in range(2):
        mods.install_modrinth("authmereloaded", server, "paper", "1.21.4",
                              "plugin")
    assert _jars(server) == ["AuthMe-6.0.1.jar"]


def test_new_version_replaces_the_old_one(make_server, monkeypatch,
                                          offline_modrinth):
    server = make_server()
    monkeypatch.setattr(mods, "_modrinth_versions",
                        lambda *a: [_version("6.0.1")])
    mods.install_modrinth("authmereloaded", server, "paper", "1.21.4",
                          "plugin")
    (server / "plugins" / "Autre-1.0.jar").write_bytes(b"x")
    monkeypatch.setattr(mods, "_modrinth_versions",
                        lambda *a: [_version("6.1.0")])
    replaced = []
    mods.install_modrinth("authmereloaded", server, "paper", "1.21.4",
                          "plugin", replaced=replaced)
    assert _jars(server) == ["AuthMe-6.1.0.jar", "Autre-1.0.jar"]
    assert replaced == ["AuthMe-6.0.1.jar"]
    manifest = json.loads((server / mods.MANIFEST).read_text("utf-8"))
    assert manifest == {"plugins/AuthMe-6.1.0.jar":
                        {"source": "modrinth", "project": "P1"}}


def test_other_projects_are_never_removed(make_server, offline_modrinth):
    server = make_server()
    a = server / "plugins" / "A-1.jar"
    b = server / "plugins" / "B-1.jar"
    for f in (a, b):
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(b"x")
    assert mods.record_install(server, a, "modrinth", "PA") == []
    assert mods.record_install(server, b, "modrinth", "PB") == []
    assert mods.record_install(server, b, "curseforge", "PA") == []
    assert _jars(server) == ["A-1.jar", "B-1.jar"]


def test_same_project_in_other_folder_is_kept(make_server, offline_modrinth):
    """Mohist : le même projet peut exister en mod et en plugin."""
    server = make_server(loader="mohist")
    mod = server / "mods" / "voice-1.jar"
    plug = server / "plugins" / "voice-1.jar"
    for f in (mod, plug):
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(b"x")
    mods.record_install(server, mod, "modrinth", "PV")
    assert mods.record_install(server, plug, "modrinth", "PV") == []
    assert mod.exists() and plug.exists()


def test_untracked_old_version_found_by_hash(make_server, monkeypatch):
    """Jar installé avant la 1.30 (absent du suivi) : reconnu par son SHA1."""
    server = make_server()
    old = server / "plugins" / "AuthMe-5.6.0.jar"
    other = server / "plugins" / "Inconnu.jar"
    new = server / "plugins" / "AuthMe-6.0.1.jar"
    for f, content in ((old, b"old"), (other, b"other"), (new, b"new")):
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(content)

    def fake_post(url, json=None, **kw):
        assert url.endswith("/version_files")
        assert mods._sha1(new) not in json["hashes"]
        return Resp(data={mods._sha1(old): {"project_id": "P1"}})
    monkeypatch.setattr(mods.requests, "post", fake_post)

    assert mods.record_install(server, new, "modrinth", "P1") == \
        ["AuthMe-5.6.0.jar"]
    assert _jars(server) == ["AuthMe-6.0.1.jar", "Inconnu.jar"]


def test_install_works_when_modrinth_lookup_fails(make_server, monkeypatch):
    server = make_server()
    new = server / "plugins" / "X-2.jar"
    old = server / "plugins" / "X-1.jar"
    for f in (old, new):
        f.parent.mkdir(exist_ok=True)
        f.write_bytes(f.name.encode())

    def boom(*a, **kw):
        raise requests.ConnectionError("hors ligne")
    monkeypatch.setattr(mods.requests, "post", boom)
    assert mods.record_install(server, new, "modrinth", "PX") == []
    assert _jars(server) == ["X-1.jar", "X-2.jar"]


# ------------------------------------------------------------ CurseForge

SECRET = "$2a$10$CLE-SECRETE-DE-TEST"


def test_curseforge_needs_a_key(monkeypatch):
    def never(*a, **kw):
        raise AssertionError("aucune requête sans clé")
    monkeypatch.setattr(mods.requests, "request", never)
    with pytest.raises(mods.ModError) as e:
        mods.search_curseforge("jei", "forge", "1.20.1", "mod", "  ")
    assert "CurseForge" in str(e.value)


@pytest.mark.parametrize("status,key", [
    (401, "cf_err_key"), (403, "cf_err_key"), (429, "cf_err_rate"),
    (404, "cf_err_notfound"), (500, "cf_err_down"), (503, "cf_err_down")])
def test_curseforge_http_errors_are_explained(monkeypatch, status, key):
    from app.i18n import STRINGS
    monkeypatch.setattr(mods.requests, "request",
                        lambda *a, **kw: Resp(status, {}))
    with pytest.raises(mods.ModError) as e:
        mods.check_curseforge_key(SECRET)
    expected = STRINGS["fr"][key].split("{")[0]
    assert str(e.value).startswith(expected)
    assert SECRET not in str(e.value)


@pytest.mark.parametrize("exc,key", [
    (requests.ConnectionError("Max retries exceeded"), "cf_err_net"),
    (requests.Timeout("lent"), "net_err_timeout")])
def test_curseforge_network_errors_are_explained(monkeypatch, exc, key):
    from app.i18n import STRINGS

    def boom(*a, **kw):
        raise exc
    monkeypatch.setattr(mods.requests, "request", boom)
    with pytest.raises(mods.ModError) as e:
        mods.search_curseforge("jei", "forge", "1.20.1", "mod", SECRET)
    assert str(e.value) == STRINGS["fr"][key]


def test_curseforge_key_is_sent_as_header_only(monkeypatch):
    seen = {}

    def fake(method, url, headers=None, **kw):
        seen.update(url=url, headers=headers, kw=kw)
        return Resp(data={"data": []})
    monkeypatch.setattr(mods.requests, "request", fake)
    assert mods.search_curseforge("jei", "forge", "1.20.1", "mod",
                                  f" {SECRET} ") == []
    assert seen["headers"]["x-api-key"] == SECRET
    assert SECRET not in seen["url"] and SECRET not in str(seen["kw"])


def test_curseforge_bad_json_is_an_error(monkeypatch):
    monkeypatch.setattr(mods.requests, "request",
                        lambda *a, **kw: Resp(200, None))
    with pytest.raises(mods.ModError):
        mods.check_curseforge_key(SECRET)


def test_explain_network_errors():
    from app.i18n import STRINGS
    fr = STRINGS["fr"]
    assert mods.explain(requests.ConnectionError("x")) == fr["net_err_offline"]
    assert mods.explain(requests.Timeout("x")) == fr["net_err_timeout"]
    assert mods.explain(requests.HTTPError(response=Resp(502))) == \
        fr["net_err_http"].format(code=502)
    assert mods.explain(mods.ModError("clair")) == "clair"


# --------------------------------------------------------------- réglages

def test_key_from_settings_then_environment(monkeypatch):
    monkeypatch.delenv(config.CF_KEY_ENV, raising=False)
    assert config.curseforge_key() == ""
    monkeypatch.setenv(config.CF_KEY_ENV, " env-key ")
    assert config.curseforge_key() == "env-key"
    s = config.load_settings()
    s["curseforge_api_key"] = "settings-key"
    config.save_settings(s)
    assert config.curseforge_key() == "settings-key"
    # la clé d'environnement n'est jamais recopiée dans le fichier
    monkeypatch.setenv(config.CF_KEY_ENV, "autre")
    assert "autre" not in config.SETTINGS_FILE.read_text("utf-8")


def test_no_key_is_shipped_with_the_app():
    assert config.DEFAULT_SETTINGS["curseforge_api_key"] == ""


def test_settings_file_survives_corruption(app_dirs):
    config.SETTINGS_FILE.write_text("{tronqué", encoding="utf-8")
    assert config.load_settings()["language"] == "fr"
    config.SETTINGS_FILE.write_text("[1, 2]", encoding="utf-8")
    assert config.load_settings()["theme"] == "dark"
    config.save_settings({"language": "en"})
    assert config.load_settings()["language"] == "en"
    assert [p.name for p in app_dirs["data"].iterdir()] == ["settings.json"]


# ------------------------------------------- dépendances et compatibilité

def _mod(number, project, deps=()):
    v = _version(number, project=project)
    v["files"][0]["filename"] = f"{project}-{number}.jar"
    v["dependencies"] = [{"project_id": p, "dependency_type": kind}
                         for p, kind in deps]
    return v


def test_required_dependencies_are_installed(make_server, monkeypatch,
                                             offline_modrinth):
    """ViaVersion sans ViaFabric = serveur Fabric qui ne démarre pas."""
    server = make_server(loader="fabric")
    catalog = {"viabackwards": [_mod("5", "VB", [("VV", "required"),
                                                 ("OPT", "optional")])],
               "VV": [_mod("5", "VV", [("VF", "required")])],
               "VF": [_mod("0.4", "VF", [("VV", "required")])]}  # cycle
    monkeypatch.setattr(mods, "_modrinth_versions",
                        lambda project, *a: catalog.get(project, []))
    monkeypatch.setattr(mods, "_server_side", lambda project: "required")
    mods.install_modrinth("viabackwards", server, "fabric", "26.2", "mod")
    assert _jars(server, "mods") == ["VB-5.jar", "VF-0.4.jar", "VV-5.jar"]
    # déjà là : rien n'est retéléchargé
    monkeypatch.setattr(mods, "download_file", lambda *a: 1 / 0)
    mods._install_deps(["VV", "VF"], "x", server / "mods" / "VB-5.jar",
                       server, "fabric", "26.2", "mod", set(), None)


def test_mod_removed_when_a_required_dependency_is_missing(
        make_server, monkeypatch, offline_modrinth):
    server = make_server(loader="fabric")
    catalog = {"easyauth": [_mod("3", "EA", [("FAPI", "required")])]}
    monkeypatch.setattr(mods, "_modrinth_versions",
                        lambda project, *a: catalog.get(project, []))
    monkeypatch.setattr(mods, "_server_side", lambda project: "required")
    with pytest.raises(mods.ModError):
        mods.install_modrinth("easyauth", server, "fabric", "26.2", "mod")
    assert _jars(server, "mods") == []


def test_client_only_mod_is_refused(make_server, monkeypatch,
                                    offline_modrinth):
    server = make_server(loader="fabric")
    monkeypatch.setattr(mods, "_modrinth_versions",
                        lambda *a: [_mod("1", "SODIUM")])
    monkeypatch.setattr(mods, "_server_side", lambda project: "unsupported")
    with pytest.raises(mods.ModError):
        mods.install_modrinth("sodium", server, "fabric", "26.2", "mod")
    assert not (server / "mods").exists()


def test_no_version_from_another_loader(monkeypatch):
    """Pas de repli sans filtre de loader : un jar Paper/Fabric dans un
    serveur Forge l'empêche de démarrer."""
    asked = []

    def fake_get(url, params=None, **kw):
        asked.append(params)
        return Resp(data=[])
    monkeypatch.setattr(mods.requests, "get", fake_get)
    assert mods._modrinth_versions("viaversion", ["forge"], "1.20.1") == []
    assert len(asked) == 1 and "loaders" in asked[0]
