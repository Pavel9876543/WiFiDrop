import socket
from unittest.mock import Mock

import dns.flags
import dns.message
import dns.rrset
import httpx
import pytest

from app.config.settings import Settings
from app.services import access_diagnostics, router_access


def test_portless_setting_applies_only_to_router(monkeypatch):
    router = Settings(_env_file=None, connection_mode="router", port=8123, http_without_port=True)
    hotspot = Settings(_env_file=None, connection_mode="hotspot", port=8123, http_without_port=True)
    assert router.effective_port == 80 and router.port == 8123
    assert hotspot.effective_port == 8123
    monkeypatch.setattr(router_access, "select_router_ip", lambda *_: "192.168.1.20")
    save = Mock()
    monkeypatch.setattr(router_access, "save_qr", save)
    payload = router_access.RouterAccess(router).start()
    assert payload["ip_url"] == "http://192.168.1.20/"
    save.assert_called_once_with(payload["ip_url"])


def test_mdns_legacy_unicast_request_reads_host_a_record(monkeypatch):
    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def bind(self, address):
            assert address == ("192.168.1.20", 0)

        def setsockopt(self, *_):
            pass

        def settimeout(self, *_):
            pass

        def sendto(self, packet, address):
            assert address == ("224.0.0.251", 5353)
            query = dns.message.from_wire(packet)
            assert query.flags == 0
            self.response = dns.message.make_response(query)
            self.response.answer.append(
                dns.rrset.from_text(
                    "otrozhka.local.",
                    120,
                    "IN",
                    "A",
                    "192.168.1.20",
                )
            )

        def recvfrom(self, *_):
            if self.response:
                response, self.response = self.response, None
                return response.to_wire(), ("192.168.1.20", 5353)
            raise TimeoutError

    monkeypatch.setattr(socket, "socket", lambda *_: FakeSocket())
    assert access_diagnostics.resolve_mdns_name("otrozhka.local", "192.168.1.20") == {
        "192.168.1.20"
    }


def test_dns_does_not_accept_unrelated_or_failed_answers():
    query = dns.message.make_query("otrozhka.", "A")
    response = dns.message.make_response(query)
    response.answer.append(dns.rrset.from_text("other.", 120, "IN", "A", "192.168.1.20"))
    assert not access_diagnostics._addresses(response, "otrozhka")
    response.answer.append(dns.rrset.from_text("otrozhka.", 120, "IN", "A", "192.168.1.99"))
    assert access_diagnostics._addresses(response, "otrozhka") == {"192.168.1.99"}
    response.flags &= ~dns.flags.QR
    assert not access_diagnostics._addresses(response, "otrozhka")


def test_http_probe_uses_direct_ip_correct_host_and_rejects_empty_page(monkeypatch):
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, content=b"")

    client_type = httpx.Client
    monkeypatch.setattr(
        access_diagnostics.httpx,
        "Client",
        lambda **kwargs: client_type(
            transport=httpx.MockTransport(handle),
            **kwargs,
        ),
    )
    with pytest.raises(ValueError, match="непустую"):
        access_diagnostics.check_http("http://192.168.1.20:8123/", "otrozhka.local")
    assert all(request.url.host == "192.168.1.20" for request in requests)
    assert all(request.headers["Host"] == "otrozhka.local:8123" for request in requests)


def test_failed_mdns_verification_falls_back_without_changing_qr(monkeypatch):
    settings = Settings(_env_file=None, connection_mode="router", local_domain="otrozhka")
    monkeypatch.setattr(router_access, "select_router_ip", lambda *_: "192.168.1.20")
    save = Mock()
    monkeypatch.setattr(router_access, "save_qr", save)
    access = router_access.RouterAccess(settings)
    monkeypatch.setattr(access, "_announce", lambda *_: None)
    monkeypatch.setattr(router_access, "check_http", lambda *_: None)
    monkeypatch.setattr(
        router_access, "diagnose_access", Mock(side_effect=ValueError("No mDNS answer"))
    )
    payload = access.start()
    assert payload["url"] == payload["ip_url"]
    access.verify()
    assert payload["domain_url"] == "" and payload["url"] == payload["ip_url"]
    assert "No mDNS answer" in payload["domain_status"]
    save.assert_called_once_with(payload["ip_url"])
    access.close()
