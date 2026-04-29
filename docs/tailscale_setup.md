# Tailscale setup — deprecated

> **Superseded by `cloudflare_tunnel.md`.**
> The campus Fortinet firewall blocks Tailscale's DERP relay (TLS interception
> breaks the connection to `derp*.tailscale.com`) and direct WireGuard UDP, so
> the Pi could not reach the VM on campus Wi-Fi. We replaced Tailscale + RPyC
> with a Cloudflare Quick Tunnel + FastAPI HTTPS service. See:
>
> - `docs/cloudflare_tunnel.md` for the new transport
> - `README.md` for the updated architecture diagram
> - `docs/rollout_guide.md` for end-to-end bring-up steps
>
> If your network does *not* block Tailscale and you prefer a private mesh,
> Tailscale still works in principle — but the code (FastAPI + bearer token)
> is now HTTP-based, not RPyC. Just point the Pi's `vm_url` at
> `http://<vm-tailscale-ip>:8000`. Nothing else changes.
