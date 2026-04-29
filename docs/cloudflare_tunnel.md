# Cloudflare Quick Tunnel — VM exposure

## Why

The campus Fortinet firewall blocks Tailscale's DERP relay (TLS interception
breaks it) and direct WireGuard UDP. We need the Pi to reach the VM's vision
service from any network. Cloudflare Quick Tunnel solves this by opening an
**outbound** HTTPS connection from the VM to Cloudflare's edge, which the
firewall sees as ordinary web traffic. The Pi then talks to a public
`https://*.trycloudflare.com` URL that fronts the VM.

- **Free, no account, no domain** — `cloudflared tunnel --url …` issues an
  ephemeral hostname per run.
- **Outbound-only** — no inbound port open on the VM, no NAT/router admin
  needed.
- **TLS terminated at the edge** — the FastAPI server only needs to bind to
  `127.0.0.1`.

## Trade-offs

- **Ephemeral URL.** Each `--url` run gets a new random subdomain. To keep the
  same hostname across reboots, register a free Named Tunnel (requires a
  Cloudflare account + a domain). For lab demos the ephemeral form is fine —
  just paste the new URL into `pi_client/config.yaml` after each VM restart.
- **Latency.** Adds ~50–100 ms per call vs. a LAN path. Acceptable because we
  do one round-trip per visitor (stop-and-authenticate), not video streaming.

## Install `cloudflared`

```bash
# Ubuntu / Debian VM
curl -L --output cloudflared.deb \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
cloudflared --version
```

## Run a Quick Tunnel by hand

In one shell, start the FastAPI server (binds 127.0.0.1:8000):

```bash
cd ~/IoT
PYTHONPATH=. python3 -m vm_server.http_server
```

In a second shell, open the tunnel:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

It prints something like:

```
Your quick Tunnel has been created! Visit it at:
  https://able-monkey-shoots-dragons.trycloudflare.com
```

Paste that URL into `pi_client/config.yaml::pi.vm_url`. Confirm from the Pi:

```bash
curl https://<your>.trycloudflare.com/ping
# {"ok":true,"service":"surveillance-vision"}
```

## Keep it up across reboots (systemd)

Save as `/etc/systemd/system/cloudflared-quick.service`:

```ini
[Unit]
Description=Cloudflare Quick Tunnel for FastAPI vision service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/cloudflared tunnel --url http://127.0.0.1:8000 --no-autoupdate
Restart=on-failure
RestartSec=5
User=ubuntu
StandardOutput=append:/var/log/cloudflared-quick.log
StandardError=append:/var/log/cloudflared-quick.log

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cloudflared-quick
sudo journalctl -fu cloudflared-quick
# grep the log for the trycloudflare.com URL after each restart:
grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /var/log/cloudflared-quick.log | tail -1
```

> Quick Tunnel URLs change on every restart. If that's painful, switch to a
> Named Tunnel: `cloudflared tunnel login` then `cloudflared tunnel create
> surveillance` and route a hostname under your zone via
> `cloudflared tunnel route dns surveillance vision.example.com`. Same daemon,
> stable URL.

## Auth

The tunnel is public; **only the bearer token gates access**. Generate one and
paste it into both configs:

```bash
openssl rand -hex 24
# put the same value in:
#   vm_server/config.yaml::server.secret_token
#   pi_client/config.yaml::pi.vm_token
```

The FastAPI server refuses to start if `secret_token` is still `CHANGE_ME`.
Rotate immediately if you ever paste the URL or token into a chat / screenshot.
