# Coturn TURN Server Setup — Thooku Madurai

Why: without a TURN server, calls between two phones on mobile data (Jio/Airtel CG-NAT)
cannot punch through, so audio fails or never connects. A TURN server relays the media.
This replaces the free `openrelay.metered.ca` fallback with your own relay — faster,
no third-party dependency, works on every network.

## 1. Get a VPS (one-time)

Any small Linux VPS with a **public IPv4** works (DigitalOcean $4/mo, Hetzner, Vultr...).
Requirement: UDP ports open. **Do not use Render for this** — Render has no UDP.

## 2. Open firewall ports

| Port(s)      | Protocol | Purpose                     |
|--------------|----------|-----------------------------|
| 3478         | UDP+TCP  | TURN/STUN listening         |
| 49160-49200  | UDP      | Media relay range           |
| 8443         | TCP      | TURN over TLS (optional)    |

Ubuntu: `ufw allow 3478/udp; ufw allow 3478/tcp; ufw allow 49160:49200/udp; ufw allow 8443/tcp`
Also open the same ports in the VPS provider's cloud firewall.

## 3. Generate credentials

```bash
docker run --rm coturn/coturn turnadmin -k -u thooku -r thookumadurai
```
Copy the long hex key into `deployment/coturn/turnuserdb.conf` (replace `0xREPLACE_WITH_TURNADMIN_KEY`).
Choose a plaintext password, e.g. `MySecretPass123`, and remember it — that's what the backend sends to clients.

## 4. Set your IP + start

Edit `deployment/coturn/coturn.conf` → uncomment `outer-ip=<YOUR_VPS_IP>`.
Then on the VPS:

```bash
# copy the deployment/ folder up, then:
cd deployment
docker compose -f docker-compose.turn.yml up -d
docker logs -f thooku_coturn   # watch for "listening on ..." and no fatal errors
```

Verify from anywhere (e.g. https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/)
— add `turn:YOUR_VPS_IP:3478` with the credentials and confirm you get a "relay" candidate.

## 5. Point the backend at it (Render)

In Render → your backend service → Environment → add:

```
TURN_SERVER_URL=turn:YOUR_VPS_IP:3478
TURN_SERVER_USERNAME=thooku
TURN_SERVER_CREDENTIAL=MySecretPass123
```

Redeploy the backend. The `/api/v1/settings/ice-config` endpoint will now return your
TURN server, and the app (`index.html`, `rider-dashboard.html`, `tracking.html`) picks it
up automatically (they load `/settings/ice-config` at startup).

## 6. Optional: TURN over TLS (port 443)

Only needed if you want `turns:` URLs (many restrictive office/public Wi-Fi only allow 443).
Requires a real certificate — see `coturn.conf` comments (`cert`/`pkey`).

## Testing after setup

1. Phone A on mobile data (caller), Phone B on mobile data (rider) — both have GPS/network.
2. Place order, restaurant accepts, rider accepts, make the in-app call.
3. Both hear each other clearly for 30+ seconds. That's the full check.
