# Tailscale setup

We use Tailscale (WireGuard mesh) so the Raspberry Pi can reach the VM's vision
service from any network — campus Wi-Fi, the lab router, a phone hotspot — with
no port forwarding or public exposure.

## Install on both ends

On the **VM**:
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                 # opens a browser auth URL once
tailscale ip -4                   # note this IP — Pi will dial it
```

On the **Raspberry Pi**:
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ping <vm-tailscale-ip>  # should succeed within a few packets
```

## Lock the RPyC port to the tailnet only

The server binds to `0.0.0.0:18861`, but the host firewall must reject anything
that didn't arrive on the `tailscale0` interface.

On the VM:
```bash
sudo ufw default deny incoming
sudo ufw allow 22/tcp                                # keep SSH
sudo ufw allow in on tailscale0 to any port 18861    # only Tailscale peers
sudo ufw enable
sudo ufw status verbose
```

Check from a non-tailnet host: `nc -zv <vm-public-ip> 18861` should hang and
fail. From the Pi: `nc -zv <vm-tailscale-ip> 18861` should connect.

## Verify the path end-to-end

From the Pi:
```bash
PYTHONPATH=. python3 -c "
import rpyc
c = rpyc.connect('<vm-tailscale-ip>', 18861, config={'sync_request_timeout': 5})
print(c.root.ping())
"
```
Expected output: `ok`.

## When things break

- `tailscale status` — both peers should be `online`.
- `journalctl -u tailscaled -f` on either end — DERP relay errors usually mean
  a campus firewall is blocking UDP; Tailscale will fall back to TCP-over-DERP
  but with higher latency. Acceptable for our load (~1 image per visitor) but
  may bump round-trip time above 1 s.
- `tailscale netcheck` — diagnoses NAT type, MTU issues, IPv6 reachability.
