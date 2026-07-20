"""Command-line interface for Cloudflare Tunnel automation."""

from __future__ import annotations

import argparse
import json
import sys

from cloudflare_tunnel.client import (
    DEFAULT_ACCOUNT,
    DEFAULT_DOMAIN,
    DEFAULT_TUNNEL,
    CloudflareAPIError,
    CloudflareConfigError,
    HetznerAPIError,
    ensure_cloudflare_dns_cname,
    ensure_hetzner_cname,
    ensure_tunnel_hostname,
    env,
    get_tunnel_ingress,
    resolve_dns_mode,
    verify_token,
)


def _token() -> str:
    token = env("CLOUDFLARE_API_TOKEN")
    if not token or token == "PLACEHOLDER":
        raise CloudflareConfigError("CLOUDFLARE_API_TOKEN missing or placeholder")
    return token


def _account(args: argparse.Namespace) -> str:
    return args.account_id or env("CLOUDFLARE_ACCOUNT_ID", DEFAULT_ACCOUNT) or DEFAULT_ACCOUNT


def _tunnel(args: argparse.Namespace) -> str:
    return args.tunnel_id or env("CLOUDFLARE_TUNNEL_ID", DEFAULT_TUNNEL) or DEFAULT_TUNNEL


def cmd_verify_token(_args: argparse.Namespace) -> int:
    try:
        result = verify_token(_token())
    except (CloudflareConfigError, CloudflareAPIError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


def cmd_list_ingress(args: argparse.Namespace) -> int:
    try:
        token = _token()
        ingress = get_tunnel_ingress(token, _account(args), _tunnel(args))
    except (CloudflareConfigError, CloudflareAPIError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if not ingress:
        print("No ingress rules.")
        return 0

    print(f"{'Hostname':<45} {'Service'}")
    print("-" * 80)
    for rule in ingress:
        hostname = rule.get("hostname") or "(catch-all)"
        print(f"{hostname:<45} {rule.get('service', '')}")
    return 0


def _ensure_dns(args: argparse.Namespace, token: str, tunnel: str) -> int:
    dns_mode = "none" if args.skip_dns else args.dns_mode
    domain = args.domain
    try:
        resolved_mode, zone_id = resolve_dns_mode(
            token,
            dns_mode,
            domain,
            args.zone_id or env("CLOUDFLARE_ZONE_ID"),
        )
    except CloudflareConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if resolved_mode == "none" and dns_mode == "auto":
        print(
            "cloudflare zone not found; skipping DNS. "
            "Add zone to Cloudflare or use --dns-mode hetzner|none."
        )
        return 0

    if resolved_mode == "cloudflare":
        assert zone_id
        changed = ensure_cloudflare_dns_cname(token, zone_id, args.hostname, tunnel, domain)
        if changed:
            print(f"cloudflare dns ensured: {args.hostname}")
        else:
            print(f"cloudflare dns up-to-date: {args.hostname}")
    elif resolved_mode == "hetzner":
        dns_token = env("HETZNER_DNS_TOKEN")
        if not dns_token:
            print("HETZNER_DNS_TOKEN not set", file=sys.stderr)
            return 2
        changed = ensure_hetzner_cname(dns_token, domain, args.hostname, tunnel)
        if changed:
            print(f"hetzner dns ensured: {args.hostname}")
        else:
            print(f"hetzner dns up-to-date: {args.hostname}")
    return 0


def cmd_ensure_hostname(args: argparse.Namespace) -> int:
    try:
        token = _token()
        account = _account(args)
        tunnel = _tunnel(args)
        changed = ensure_tunnel_hostname(token, account, tunnel, args.hostname, args.origin)
        if changed:
            print(f"tunnel ingress ensured: {args.hostname} -> {args.origin}")
        else:
            print(f"tunnel ingress up-to-date: {args.hostname} -> {args.origin}")
        return _ensure_dns(args, token, tunnel)
    except (CloudflareConfigError, CloudflareAPIError, HetznerAPIError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def cmd_ensure_dns(args: argparse.Namespace) -> int:
    try:
        token = _token()
        return _ensure_dns(args, token, _tunnel(args))
    except (CloudflareConfigError, CloudflareAPIError, HetznerAPIError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cloudflare Tunnel ingress and DNS automation",
    )
    parser.add_argument("--account-id", default=None, help="Cloudflare account id")
    parser.add_argument("--tunnel-id", default=None, help="Cloudflare tunnel id")
    parser.add_argument("--domain", default=DEFAULT_DOMAIN, help="Managed DNS domain")
    parser.add_argument("--zone-id", default=None, help="Cloudflare zone id (optional)")

    sub = parser.add_subparsers(dest="command", required=True)

    verify = sub.add_parser("verify-token", help="Verify CLOUDFLARE_API_TOKEN")
    verify.set_defaults(func=cmd_verify_token)

    list_ingress = sub.add_parser("list-ingress", help="List tunnel ingress rules")
    list_ingress.set_defaults(func=cmd_list_ingress)

    ensure_hostname = sub.add_parser(
        "ensure-hostname",
        help="Idempotent tunnel hostname + optional DNS",
    )
    ensure_hostname.add_argument("--hostname", required=True)
    ensure_hostname.add_argument("--origin", default="http://127.0.0.1:80")
    ensure_hostname.add_argument(
        "--dns-mode",
        choices=("auto", "cloudflare", "hetzner", "none"),
        default="auto",
    )
    ensure_hostname.add_argument("--skip-dns", action="store_true")
    ensure_hostname.set_defaults(func=cmd_ensure_hostname)

    ensure_dns = sub.add_parser("ensure-dns", help="Ensure DNS only (no ingress change)")
    ensure_dns.add_argument("--hostname", required=True)
    ensure_dns.add_argument(
        "--mode",
        dest="dns_mode",
        choices=("auto", "cloudflare", "hetzner", "none"),
        required=True,
    )
    ensure_dns.add_argument("--skip-dns", action="store_true")
    ensure_dns.set_defaults(func=cmd_ensure_dns)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
