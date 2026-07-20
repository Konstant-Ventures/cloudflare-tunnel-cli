"""Cloudflare Tunnel and DNS API client (stdlib only)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"
HETZNER_API = "https://api.hetzner.cloud/v1"
DEFAULT_ACCOUNT = "efd00c02c0d80bc0134f3327662f857b"
DEFAULT_TUNNEL = "8ef15b8b-528a-4621-826d-b003f795474a"
DEFAULT_DOMAIN = "hectorsanchez.eu"


class CloudflareConfigError(Exception):
    """Missing or invalid configuration."""


class CloudflareAPIError(Exception):
    """Cloudflare API request failed."""


class HetznerAPIError(Exception):
    """Hetzner DNS API request failed."""


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key) or default


def cf_request(token: str, method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:800]
        raise CloudflareAPIError(f"Cloudflare API {exc.code} {path}: {detail}") from exc


def verify_token(token: str) -> dict:
    data = cf_request(token, "GET", "/user/tokens/verify")
    if not data.get("success"):
        raise CloudflareAPIError(f"Token verify failed: {data}")
    return data.get("result") or {}


def get_tunnel_ingress(token: str, account: str, tunnel: str) -> list[dict]:
    data = cf_request(token, "GET", f"/accounts/{account}/cfd_tunnel/{tunnel}/configurations")
    result = data.get("result") or {}
    config = result.get("config") or {}
    return list(config.get("ingress") or [])


def ensure_tunnel_hostname(
    token: str,
    account: str,
    tunnel: str,
    hostname: str,
    origin: str,
) -> bool:
    ingress = get_tunnel_ingress(token, account, tunnel)
    rules = [r for r in ingress if r.get("hostname")]
    catch_all = next((r for r in ingress if not r.get("hostname")), {"service": "http_status:404"})

    existing = next((r for r in rules if r.get("hostname") == hostname), None)
    if existing and existing.get("service") == origin:
        return False

    if existing:
        existing["service"] = origin
    else:
        rules.append({"hostname": hostname, "service": origin})

    rules.append(catch_all if catch_all.get("service") else {"service": "http_status:404"})
    cf_request(
        token,
        "PUT",
        f"/accounts/{account}/cfd_tunnel/{tunnel}/configurations",
        {"config": {"ingress": rules}},
    )
    return True


def cf_zone_id(token: str, domain: str) -> str | None:
    data = cf_request(token, "GET", f"/zones?name={domain}")
    zones = data.get("result") or []
    if not zones:
        return None
    return zones[0]["id"]


def hetzner_zone_id(dns_token: str, domain: str) -> str:
    req = urllib.request.Request(
        f"{HETZNER_API}/zones",
        headers={"Authorization": f"Bearer {dns_token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            zones = json.loads(resp.read()).get("zones", [])
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:500]
        raise HetznerAPIError(f"Hetzner API {exc.code}: {detail}") from exc
    for zone in zones:
        if zone.get("name") == domain:
            return str(zone["id"])
    raise HetznerAPIError(f"Hetzner zone not found: {domain}")


def ensure_cloudflare_dns_cname(
    token: str,
    zone_id: str,
    hostname: str,
    tunnel_id: str,
    domain: str = DEFAULT_DOMAIN,
) -> bool:
    suffix = f".{domain}"
    if not hostname.endswith(suffix):
        raise ValueError(f"hostname {hostname} not under {domain}")
    name = hostname[: -len(suffix)]
    target = f"{tunnel_id}.cfargotunnel.com"

    existing = cf_request(token, "GET", f"/zones/{zone_id}/dns_records?name={hostname}&type=CNAME")
    records = existing.get("result") or []
    for rec in records:
        if rec.get("content") == target and rec.get("proxied"):
            return False
        cf_request(
            token,
            "PATCH",
            f"/zones/{zone_id}/dns_records/{rec['id']}",
            {"type": "CNAME", "name": name, "content": target, "proxied": True, "ttl": 1},
        )
        return True

    cf_request(
        token,
        "POST",
        f"/zones/{zone_id}/dns_records",
        {"type": "CNAME", "name": name, "content": target, "proxied": True, "ttl": 1},
    )
    return True


def ensure_hetzner_cname(
    dns_token: str,
    domain: str,
    hostname: str,
    tunnel_id: str,
    ttl: int = 300,
) -> bool:
    if not hostname.endswith(f".{domain}"):
        raise ValueError(f"hostname {hostname} not under domain {domain}")
    name = hostname[: -len(domain) - 1]
    target = f"{tunnel_id}.cfargotunnel.com."
    zone_id = hetzner_zone_id(dns_token, domain)

    req = urllib.request.Request(
        f"{HETZNER_API}/zones/{zone_id}/rrsets",
        headers={"Authorization": f"Bearer {dns_token}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        rrsets = json.loads(resp.read()).get("rrsets", [])

    for rr in rrsets:
        if rr.get("name") == name and rr.get("type") == "CNAME":
            vals = [rec["value"] for rec in rr.get("records", [])]
            if target in vals and (rr.get("ttl") or ttl) == ttl:
                return False
            payload = json.dumps({"records": [{"value": target}], "ttl": ttl}).encode()
            upd = urllib.request.Request(
                f"{HETZNER_API}/zones/{zone_id}/rrsets/{name}/CNAME/actions/update_records",
                data=payload,
                headers={"Authorization": f"Bearer {dns_token}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(upd, timeout=30):
                pass
            return True

    for rr in rrsets:
        if rr.get("name") != name:
            continue
        rtype = rr.get("type")
        if rtype == "CNAME":
            continue
        delete = urllib.request.Request(
            f"{HETZNER_API}/zones/{zone_id}/rrsets/{name}/{rtype}",
            headers={"Authorization": f"Bearer {dns_token}"},
            method="DELETE",
        )
        with urllib.request.urlopen(delete, timeout=30):
            pass

    payload = json.dumps(
        {"name": name, "type": "CNAME", "ttl": ttl, "records": [{"value": target}]}
    ).encode()
    create = urllib.request.Request(
        f"{HETZNER_API}/zones/{zone_id}/rrsets",
        data=payload,
        headers={"Authorization": f"Bearer {dns_token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(create, timeout=30):
            pass
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            req2 = urllib.request.Request(
                f"{HETZNER_API}/zones/{zone_id}/rrsets",
                headers={"Authorization": f"Bearer {dns_token}"},
            )
            with urllib.request.urlopen(req2, timeout=30) as resp:
                rrsets2 = json.loads(resp.read()).get("rrsets", [])
            for rr in rrsets2:
                if rr.get("name") == name and rr.get("type") == "CNAME":
                    vals = [rec["value"] for rec in rr.get("records", [])]
                    if target in vals:
                        return False
        raise
    return True


def resolve_dns_mode(
    token: str,
    dns_mode: str,
    domain: str,
    zone_id: str | None,
) -> tuple[str, str | None]:
    if dns_mode == "none":
        return "none", zone_id
    if dns_mode == "auto":
        resolved_zone = zone_id or cf_zone_id(token, domain)
        return ("cloudflare" if resolved_zone else "none"), resolved_zone
    if dns_mode == "cloudflare":
        resolved_zone = zone_id or cf_zone_id(token, domain)
        if not resolved_zone:
            raise CloudflareConfigError("Cloudflare zone not found for cloudflare dns mode")
        return "cloudflare", resolved_zone
    if dns_mode == "hetzner":
        return "hetzner", zone_id
    raise CloudflareConfigError(f"Unknown dns mode: {dns_mode}")
