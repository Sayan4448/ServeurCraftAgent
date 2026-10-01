"""Garde-fous de base : imports, traductions, isolation des données."""
import importlib
import pkgutil
import string

import app
from app import config
from app.i18n import LANGS, STRINGS


def test_all_modules_import():
    for mod in pkgutil.walk_packages(app.__path__, "app."):
        importlib.import_module(mod.name)


def test_translations_complete():
    keys = set(STRINGS["fr"])
    for lang in LANGS:
        assert set(STRINGS[lang]) == keys, lang


def test_translations_same_placeholders():
    fmt = string.Formatter()

    def fields(text):
        return {name for _, name, _, _ in fmt.parse(text) if name}
    for key, text in STRINGS["fr"].items():
        for lang in LANGS:
            assert fields(STRINGS[lang][key]) == fields(text), (key, lang)


def test_data_dirs_are_isolated(app_dirs):
    assert config.SERVERS_DIR == app_dirs["servers"]
    assert config.load_settings()["language"] == "fr"
