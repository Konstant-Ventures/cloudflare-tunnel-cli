from cloudflare_tunnel.client import ensure_tunnel_hostname, resolve_dns_mode


def test_ensure_tunnel_hostname_noop_when_unchanged():
    calls = []

    def fake_get_ingress(_token, _account, _tunnel):
        return [
            {"hostname": "app.example.com", "service": "http://127.0.0.1:80"},
            {"service": "http_status:404"},
        ]

    def fake_cf_request(_token, method, path, body=None):
        calls.append((method, path, body))
        return {"success": True}

    import cloudflare_tunnel.client as client

    original_get = client.get_tunnel_ingress
    original_cf = client.cf_request
    client.get_tunnel_ingress = fake_get_ingress
    client.cf_request = fake_cf_request
    try:
        changed = ensure_tunnel_hostname("tok", "acct", "tun", "app.example.com", "http://127.0.0.1:80")
    finally:
        client.get_tunnel_ingress = original_get
        client.cf_request = original_cf

    assert changed is False
    assert calls == []


def test_resolve_dns_mode_auto_without_zone():
    import cloudflare_tunnel.client as client

    original = client.cf_zone_id
    client.cf_zone_id = lambda _token, _domain: None
    try:
        mode, zone = resolve_dns_mode("tok", "auto", "example.com", None)
    finally:
        client.cf_zone_id = original
    assert mode == "none"
    assert zone is None
