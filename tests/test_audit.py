"""Vérification des mods / plugins installés : fichiers qui ne peuvent pas
marcher sur le serveur (mod client, autre loader, Java trop récent)."""
import json
import zipfile

from app.core import modpack, mods


def _jar(path, files):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def _fabric(env="*"):
    return {"fabric.mod.json": json.dumps({"id": "x", "environment": env})}


FORGE_CLIENT = {"META-INF/mods.toml": '''
[[mods]]
modId="minimap"
[[dependencies.minimap]]
modId="minecraft"
mandatory=true
side="CLIENT"
'''}
FORGE = {"META-INF/mods.toml": '[[mods]]\nmodId="create"\n'}


def test_audit_flags_client_and_wrong_loader_mods(make_server):
    server = make_server(loader="fabric", mc_version="1.21.4")
    _jar(server / "mods" / "lithium.jar", _fabric())
    _jar(server / "mods" / "sodium.jar", _fabric("client"))
    _jar(server / "mods" / "create-forge.jar", FORGE)
    _jar(server / "mods" / "lib-sans-metadonnees.jar", {"a.class": b""})
    found = {i["name"]: i["reason"] for i in mods.audit(
        server, "fabric", "1.21.4", online=False)}
    assert found == {"sodium.jar": "client", "create-forge.jar": "loader"}


def test_audit_forge_client_only_and_old_plugin_java(make_server):
    forge = make_server("f", loader="forge", mc_version="1.20.1")
    _jar(forge / "mods" / "minimap.jar", FORGE_CLIENT)
    _jar(forge / "mods" / "create.jar", FORGE)
    assert [(i["name"], i["reason"]) for i in mods.audit(
        forge, "forge", "1.20.1", online=False)] == [("minimap.jar", "client")]
    paper = make_server("p", loader="paper", mc_version="1.16.5")
    _jar(paper / "plugins" / "AuthMe.jar", {
        "plugin.yml": "main: a.Main\n",
        "a/Main.class": b"\xca\xfe\xba\xbe\x00\x00\x00\x3d"})   # Java 17
    issue, = mods.audit(paper, "paper", "1.16.5", online=False)
    assert (issue["reason"], issue["detail"]) == ("java", "17")
    assert "17" in mods.audit_text(issue, "paper", "1.16.5")


def test_disabled_mod_is_kept_but_ignored(make_server):
    server = make_server(loader="fabric")
    jar = _jar(server / "mods" / "sodium.jar", _fabric("client"))
    off = mods.set_enabled(str(jar), False)
    assert off.name == "sodium.jar.disabled" and not jar.exists()
    assert mods.audit(server, "fabric", "1.21.4", online=False) == []
    item, = mods.list_installed(server, "fabric")
    assert item["disabled"] and item["name"] == "sodium.jar"
    assert mods.set_enabled(item["path"], True) == jar and jar.exists()


def test_modpack_forge_jar_without_side_info_falls_back_to_known_list(
        monkeypatch):
    """Un mods.toml sans mention ne prouve rien : un mod client connu
    (minimap, shaders…) non référencé par Modrinth restait installé."""
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("META-INF/mods.toml", FORGE["META-INF/mods.toml"])
    items = [{"name": "Xaeros_Minimap_24.jar", "data": buf.getvalue()},
             {"name": "create-1.20.1.jar", "data": buf.getvalue()}]
    monkeypatch.setattr(modpack, "_modrinth_sides", lambda hashes: {})
    modpack._classify(items)
    assert [it["side"] for it in items] == ["client", "unknown"]
