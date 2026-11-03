"""Terminal OpenCode : pont MCP local et configuration d'OpenCode (aucun
réseau extérieur, aucun opencode réel)."""
import json
import urllib.error
import urllib.request

import pytest

from app.ai import opencode
from app.ai.mcp_bridge import INSTRUCTIONS, Bridge

_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@pytest.fixture
def bridge(make_server):
    make_server("test")
    b = Bridge("test")
    yield b
    b.close()


def _rpc(bridge, method, params=None, token=None, mid=1):
    body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if mid is not None:
        body["id"] = mid
    req = urllib.request.Request(
        bridge.url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 "Authorization": f"Bearer {token or bridge.token}"})
    with _NO_PROXY.open(req, timeout=10) as r:
        raw = r.read()
        return r.status, json.loads(raw) if raw else None


def test_bridge_listens_on_loopback_only(bridge):
    assert bridge.httpd.server_address[0] == "127.0.0.1"
    assert bridge.url.startswith("http://127.0.0.1:")


def test_bridge_mcp_handshake_and_tools(bridge):
    status, res = _rpc(bridge, "initialize",
                       {"protocolVersion": "2025-03-26", "capabilities": {},
                        "clientInfo": {"name": "pytest", "version": "1"}})
    assert status == 200
    assert res["result"]["protocolVersion"] == "2025-03-26"
    assert "tools" in res["result"]["capabilities"]
    assert _rpc(bridge, "notifications/initialized", mid=None) == (202, None)

    tools = {t["name"]: t for t in _rpc(bridge, "tools/list")[1]
             ["result"]["tools"]}
    assert {"list_tunnels", "setup_playit_tunnels", "server_status",
            "start_server", "read_file", "install_mod"} <= set(tools)
    assert tools["read_file"]["inputSchema"]["required"] == ["path"]

    info = _rpc(bridge, "tools/call", {"name": "server_info",
                                       "arguments": {}})[1]["result"]
    assert not info["isError"]
    assert json.loads(info["content"][0]["text"])["loader"] == "paper"
    files = _rpc(bridge, "tools/call", {"name": "list_files",
                                        "arguments": {"subdir": ""}})[1]
    assert "servercraft.json" in files["result"]["content"][0]["text"]
    tun = _rpc(bridge, "tools/call", {"name": "list_tunnels"})[1]["result"]
    assert json.loads(tun["content"][0]["text"])["tunnels"] == []


def test_bridge_tool_errors_are_results(bridge):
    for name, args in (("read_file", {"path": "../../data/settings.json"}),
                       ("read_file", {}),           # argument manquant
                       ("nope", {}),
                       ("setup_playit_tunnels", {})):   # compte non lié
        res = _rpc(bridge, "tools/call", {"name": name,
                                          "arguments": args})[1]["result"]
        assert res["isError"], name
    assert _rpc(bridge, "ping")[1]["result"] == {}
    assert _rpc(bridge, "resources/list")[1]["error"]["code"] == -32601


def test_bridge_rejects_bad_token(bridge):
    with pytest.raises(urllib.error.HTTPError) as e:
        _rpc(bridge, "tools/list", token="mauvais")
    assert e.value.code == 401


def test_opencode_config_points_to_bridge(app_dirs):
    path = opencode.write_config("http://127.0.0.1:5555/mcp", "tok",
                                 INSTRUCTIONS)
    assert path.parent == app_dirs["data"] / "opencode"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    mcp = cfg["mcp"]["servercraft"]
    assert mcp["type"] == "remote" and mcp["enabled"] and mcp["oauth"] is False
    assert mcp["url"] == "http://127.0.0.1:5555/mcp"
    assert mcp["headers"] == {"Authorization": "Bearer tok"}
    rules = cfg["instructions"][0]
    assert "\\" not in rules
    assert "servercraft" in open(rules, encoding="utf-8").read()
    assert opencode._env(path)["OPENCODE_CONFIG"] == str(path)


def test_opencode_json_events():
    ev = lambda **kw: json.dumps({"sessionID": "ses_1", **kw})  # noqa: E731
    assert opencode.parse_event(ev(type="text", part={"text": " Salut \n"})) \
        == ("Salut", "ses_1")
    assert opencode.parse_event(ev(type="tool_use", part={
        "tool": "servercraft_server_status",
        "state": {"status": "completed", "title": "ok"}}))[0] == \
        "⚙ servercraft_server_status — ok"
    assert opencode.parse_event(ev(type="tool_use", part={
        "tool": "bash", "state": {"status": "error", "error": "refusé"}}))[0] \
        == "✗ bash : refusé"
    assert opencode.parse_event(ev(type="error", error={
        "name": "ProviderAuthError", "data": {"message": "no key"}}))[0] == \
        "✖ no key"
    assert opencode.parse_event(ev(type="step_finish", part={})) == \
        ("", "ses_1")
    assert opencode.parse_event("Error: model not found\n") == \
        ("Error: model not found", "")
