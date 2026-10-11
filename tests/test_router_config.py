"""Проверяем границы изменений роутера и реальную доступность операций API."""

import hashlib
import json

import httpx
import pytest

from app.services import router_config
from app.services.router_config import RouterClient, RouterConfigError, RouterConnection


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://example.org",
        "https://8.8.8.8",
        "http://127.0.0.1",
        "http://192.168.1.1/secret",
        "http://user:password@192.168.1.1",
        "http://192.168.1.1?password=secret",
    ],
)
def test_rejects_non_lan_and_credential_urls(endpoint):
    with pytest.raises(ValueError):
        RouterConnection(endpoint, "mikrotik", "admin", "secret")


def make_client(provider, handler):
    client = RouterClient(RouterConnection("https://192.168.1.1", provider, "admin", "secret"))
    client.http.close()
    client.http = httpx.Client(
        base_url="https://192.168.1.1",
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )
    return client


def mikrotik_handler(entries, requests, *, write=True, dns_enabled=True):
    def handle(request):
        requests.append(request)
        if request.method == "GET":
            value = {
                "/rest/system/resource": [{"platform": "MikroTik", "version": "7.21"}],
                "/rest/ip/dns": {"allow-remote-requests": "true" if dns_enabled else "false"},
                "/rest/ip/dns/static": entries,
                "/rest/user": [{"name": "admin", "group": "test"}],
                "/rest/user/group": [{"name": "test", "policy": "read,write" if write else "read"}],
            }[request.url.path]
            return httpx.Response(200, json=value)
        value = json.loads(request.content)
        if request.method == "PUT":
            entries.append({".id": "*1", **value})
        elif request.method == "PATCH":
            entries[0].update(value)
        else:
            raise AssertionError(f"Unexpected write: {request.method} {request.url.path}")
        return httpx.Response(200, json=value)

    return handle


@pytest.mark.parametrize(("write", "dns_enabled"), [(True, True), (False, True), (True, False)])
def test_mikrotik_probe_never_writes_and_checks_permissions(write, dns_enabled):
    requests = []
    with make_client(
        "mikrotik", mikrotik_handler([], requests, write=write, dns_enabled=dns_enabled)
    ) as client:
        assert client.probe().supported == (write and dns_enabled)
        assert all(request.method == "GET" for request in requests)
        assert "secret" not in repr(client.connection)


def test_mikrotik_create_then_update_only_owned_record(monkeypatch):
    entries, requests = [], []
    monkeypatch.setattr(router_config, "resolve_router_name", lambda *_: {"192.168.1.20"})
    with make_client("mikrotik", mikrotik_handler(entries, requests)) as client:
        assert "ответ проверен" in client.configure_dns("otrozhka", "192.168.1.20")
        assert entries[0]["name"] == "otrozhka"
        assert entries[0]["comment"] == "WiFiDrop"
        entries[0]["address"] = "192.168.1.99"
        client.configure_dns("otrozhka", "192.168.1.20")
        assert entries[0]["address"] == "192.168.1.20"
    assert [r.method for r in requests if r.method != "GET"] == ["PUT", "PATCH"]


def test_mikrotik_does_not_replace_foreign_record(monkeypatch):
    entries = [{".id": "*1", "name": "otrozhka", "address": "192.168.1.99"}]
    requests = []
    with (
        make_client("mikrotik", mikrotik_handler(entries, requests)) as client,
        pytest.raises(RouterConfigError, match="чужой"),
    ):
        client.configure_dns("otrozhka", "192.168.1.20")
    assert all(r.method == "GET" for r in requests)
    assert entries[0]["address"] == "192.168.1.99"


def test_redirect_is_not_followed_and_errors_hide_secrets():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "https://example.org/secret"})

    with make_client("mikrotik", handle) as client:
        capability = client.probe()
    assert not capability.supported
    assert len(requests) == 1
    assert "secret" not in capability.message


def openwrt_handler(entries, calls, *, write=True):
    def handle(request):
        body = json.loads(request.content)
        token, obj, method, args = body["params"]
        calls.append((obj, method, args))
        if obj == "session" and method == "login":
            result = {"ubus_rpc_session": "a" * 32}
        else:
            assert token == "a" * 32
            if (obj, method) == ("system", "board"):
                result = {"release": {"distribution": "OpenWrt"}}
            elif (obj, method) == ("session", "access"):
                result = {"access": write}
            elif (obj, method) == ("uci", "get"):
                result = {"values": entries}
            elif (obj, method) == ("uci", "add"):
                assert args["config"] == "dhcp" and args["type"] == "domain"
                entries[args["name"]] = {".type": "domain", **args["values"]}
                result = {"section": args["name"]}
            elif (obj, method) == ("uci", "set"):
                assert args["config"] == "dhcp"
                entries[args["section"]].update(args["values"])
                result = {}
            elif (obj, method) in {
                ("uci", "apply"),
                ("uci", "confirm"),
                ("uci", "rollback"),
                ("session", "destroy"),
            }:
                result = {}
            else:
                raise AssertionError(f"Unexpected RPC: {obj}.{method}")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": [0, result]})

    return handle


@pytest.mark.parametrize("write", [True, False])
def test_openwrt_probe_and_session_cleanup(write):
    calls = []
    with make_client(
        "openwrt", openwrt_handler({"dns": {".type": "dnsmasq"}}, calls, write=write)
    ) as client:
        assert client.probe().supported is write
    assert ("session", "destroy", {}) in calls
    assert not any(obj == "uci" and method in {"add", "set", "apply"} for obj, method, _ in calls)


@pytest.mark.parametrize("valid_dns", [True, False])
def test_openwrt_apply_confirms_dns_or_rolls_back(monkeypatch, valid_dns):
    entries = {"dns": {".type": "dnsmasq"}}
    calls = []
    with make_client("openwrt", openwrt_handler(entries, calls)) as client:
        if valid_dns:
            monkeypatch.setattr(client, "_verify_dns", lambda *_: None)
            client.configure_dns("otrozhka", "192.168.1.20")
        else:

            def fail(*_):
                raise RouterConfigError("DNS mismatch")

            monkeypatch.setattr(client, "_verify_dns", fail)
            with pytest.raises(RouterConfigError, match="откат"):
                client.configure_dns("otrozhka", "192.168.1.20")
    assert ("uci", "apply", {"rollback": True, "timeout": 30}) in calls
    assert (("uci", "confirm", {}) in calls) is valid_dns
    assert (("uci", "rollback", {}) in calls) is not valid_dns
    writes = [
        (method, args) for obj, method, args in calls if obj == "uci" and method in {"add", "set"}
    ]
    assert len(writes) == 1 and writes[0][1]["config"] == "dhcp"
    assert "network" not in entries


def test_openwrt_section_collision_does_not_write():
    section = "wifidrop_" + hashlib.sha256(b"otrozhka").hexdigest()[:16]
    entries = {"dns": {".type": "dnsmasq"}, section: {".type": "domain", "name": "different"}}
    calls = []
    with (
        make_client("openwrt", openwrt_handler(entries, calls)) as client,
        pytest.raises(RouterConfigError, match="чужой"),
    ):
        client.configure_dns("otrozhka", "192.168.1.20")
    assert not any(obj == "uci" and method in {"set", "add", "apply"} for obj, method, _ in calls)
