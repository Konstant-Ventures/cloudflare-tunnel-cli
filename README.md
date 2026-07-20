# cloudflare-tunnel-cli

> Idempotent CLI for Cloudflare Tunnel ingress and optional DNS automation.

## Installation

```bash
pip install git+https://github.com/Konstant-Ventures/cloudflare-tunnel-cli.git
# or from this lab clone:
pip install -e refs/cloudflare-tunnel-cli
```

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `CLOUDFLARE_API_TOKEN` | yes | Account Tunnel Edit (+ Zone DNS when using Cloudflare DNS) |
| `CLOUDFLARE_ACCOUNT_ID` | no | Default account in use for konstant-server |
| `CLOUDFLARE_TUNNEL_ID` | no | Default `konstant-server` tunnel UUID |
| `CLOUDFLARE_ZONE_ID` | no | Skip zone lookup when set |
| `HETZNER_DNS_TOKEN` | for `--dns-mode hetzner` | Legacy external CNAME (does not proxy) |

**Never reuse** production `CLOUDFLARE_TUNNEL_TOKEN` (connector) as the API token.

## Commands

```bash
cloudflare-tunnel verify-token
cloudflare-tunnel list-ingress
cloudflare-tunnel ensure-hostname \
  --hostname demo-static-konstant.hectorsanchez.eu \
  --origin http://127.0.0.1:80 \
  --dns-mode none
cloudflare-tunnel ensure-dns \
  --hostname demo-static-konstant.hectorsanchez.eu \
  --mode none
```

### DNS modes

| Mode | Behavior |
|------|----------|
| `auto` | Proxied Cloudflare CNAME when zone exists; else skip |
| `cloudflare` | Require zone; create proxied CNAME |
| `hetzner` | External CNAME (non-proxying; interim eval uses VPS A instead) |
| `none` | Tunnel ingress only |

Public HTTPS via tunnel requires **proxied CNAME in the same Cloudflare account** as the tunnel. Until `hectorsanchez.eu` is on Cloudflare, use interim VPS TLS proxy or Tailscale Funnel for eval.

## Platform Control

Set on konstant when mutations are enabled:

```bash
PLATFORM_CONTROL_EDGE_PROVIDER=cloudflare-tunnel
PLATFORM_CONTROL_CF_TUNNEL_EXECUTABLE=/usr/local/bin/cloudflare-tunnel
PLATFORM_CONTROL_CF_TUNNEL_DNS_MODE=none
CLOUDFLARE_API_TOKEN=...
```

VPS production keeps `PLATFORM_CONTROL_EDGE_PROVIDER=hetzner` with Hetzner A records.

## Related

- Lab runbook: [`runbooks/10-parallel-evaluation.md`](../../runbooks/10-parallel-evaluation.md)
- Decision: [`decisions/2026-07-20-parallel-vps-konstant-evaluation.md`](../../decisions/2026-07-20-parallel-vps-konstant-evaluation.md)
