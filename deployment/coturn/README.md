# Coturn TURN Server Setup — Thooku Madurai

Why: without a TURN server, calls between two phones on mobile data (Jio/Airtel CG-NAT)
cannot punch through, so audio fails or never connects. A TURN server relays the media.
This replaces the free `openrelay.metered.ca` fallback with your own relay — faster,
no third-party dependency, works on every network.

## 1. Get a VM: Oracle Cloud Always Free (free)

Create a free account at https://www.oracle.com/cloud/free/ then:

1. **Region:** choose **Mumbai** (Maharashtra) or **Hyderabad** (nearest to Madurai).
2. **Create a VM instance**: menu → Compute → Instances → Create instance.
   - Image: **Ubuntu 22.04**
   - Shape: **Ampere A1.Flex** (ARM). Under *Always Free eligible* it lets you pick
     **OCPU: 2, RAM: 12 GB** for free (total free allowance is 4 OCPU / 24 GB,
     so that's within limits).
   - Add your **SSH public key**.
3. Note the instance **private IP** in "Primary VNIC" (looks like `10.0.0.x`).

Cost: ₹0 — fire up, no charges. Always Free gives 10 TB/month egress (far more than
your call volume), but set **Budget alerts to ₹0** and keep the VM busy (Coturn runs
24/7, so it won't be reclaimed as idle).

## 2. Open firewall ports (TWO places)

**a) Ubuntu ufw on the VM:**

```bash
sudo ufw allow 3478/udp
sudo ufw allow 3478/tcp
sudo ufw allow 49160:49200/udp
sudo ufw allow 22/tcp
sudo ufw enable
```

**b) Oracle VCN Security List** (this step is mandatory on Oracle — no ports are open by
default): Virtual Cloud Network → your VCN → **Security Lists** → Default Security List →
Add Ingress Rules. Add all 4 rules, source CIDR `0.0.0.0/0`:

| Source        | IP Protocol    | Destination Port | Purpose              |
|---------------|----------------|------------------|----------------------|
| 0.0.0.0/0     | UDP            | 3478             | TURN/STUN            |
| 0.0.0.0/0     | TCP            | 3478             | TURN/STUN (TCP)      |
| 0.0.0.0/0     | UDP            | 49160-49200      | Media relay range    |
| 0.0.0.0/0     | TCP            | 22               | SSH                  |

## 3. Copy the folder up + install Docker + run setup (one shot)

```bash
# local: push latest first (git add -A; git commit; git push), then on the VM:
git clone <your-repo-url> && cd thooku  # or scp the deployment/ folder up

# install Docker (Oracle ARM Ubuntu 22.04)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker

# one-shot setup: detects IP, writes coturn.conf + turnuserdb.conf, starts Coturn,
# and prints the env vars to paste into Render:
bash deployment/coturn/setup.sh
```

`setup.sh` handles the Oracle quirk that VMs have a private IP behind NAT: it writes
`external-ip=PUBLIC/PRIVATE` into `coturn.conf` so relay candidates advertise the
public IP. Verify with `docker logs thooku_coturn` — expect `listening on` and no
fatal errors.

Verify from anywhere (e.g. https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/)
— add `turn:YOUR_VPS_IP:3478` with the printed username/password and confirm you get a
"relay" candidate. Must show `turn:` with `relay`.

## 4. Point the backend at it (Render)

Copy the three values `setup.sh` printed and add them in Render → your backend service
→ Environment → Save → **Manual Deploy → Deploy latest commit**.

```
TURN_SERVER_URL=turn:YOUR_VPS_IP:3478?transport=udp
TURN_SERVER_USERNAME=thooku
TURN_SERVER_CREDENTIAL=<password shown by setup.sh>
```

The `/api/v1/settings/ice-config` endpoint now returns your TURN server, and the app
(`index.html`, `rider-dashboard.html`, `tracking.html`) picks it up automatically for
every user (old + new) without any client change.

## 5. Optional: TURN over TLS (port 443)

Only needed if you want `turns:` URLs (very restrictive networks that block everything
but 443). Requires a free real certificate (`certbot -d subdomain.yourdomain.com`),
then point `cert=`/`pkey=` in `coturn.conf`. Skip for now.

## Testing after setup

1. Phone A on mobile data (caller), Phone B on mobile data (rider) — both have GPS/network.
2. Place order, restaurant accepts, rider accepts, make the in-app call.
3. Both hear each other clearly for 30+ seconds. That's the full check.
4. Repeat once with **Wi-Fi off on the caller** (pure 4G/5G) — this is the case that
   used to fail and now goes through your relay.