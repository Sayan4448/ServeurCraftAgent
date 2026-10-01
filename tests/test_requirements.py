"""Chaque module tiers importé par l'app doit être dans requirements.txt."""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# nom d'import -> nom du paquet pip quand ils diffèrent
PIP_NAMES = {"PIL": "pillow"}


def _third_party_imports():
    found = set()
    for f in [ROOT / "main.py", *(ROOT / "app").rglob("*.py")]:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                found.add(node.module.split(".")[0])
    return {m for m in found
            if m != "app" and m not in sys.stdlib_module_names}


def test_requirements_cover_imports():
    declared = {re.split(r"[<>=!~\[ ]", line.strip(), maxsplit=1)[0].lower()
                for line in (ROOT / "requirements.txt").read_text(
                    encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")}
    missing = {m for m in _third_party_imports()
               if PIP_NAMES.get(m, m).lower() not in declared}
    assert not missing, f"absents de requirements.txt : {sorted(missing)}"
