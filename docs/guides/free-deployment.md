# Deploying AssureOps for free

AssureOps is one Docker stack:
- portals, API, workers and Keycloak;
- Postgres, Redis and an object store;
- local models (Ollama plus a small encoder service).

The models need about 8–10 GB of RAM, so most free "app hosting" tiers (Render, Railway, Fly.io free plans) are too small. The free option that fits the whole stack is one **Oracle Cloud Always Free** virtual machine.

| Need | Free option |
|---|---|
| Server | Oracle Cloud Always Free, Ampere A1: 4 ARM cores, 24 GB RAM, 200 GB disk (a card is needed to sign up; Always Free resources are not charged) |
| Public address with HTTPS | A free DuckDNS subdomain (e.g. `assureops.duckdns.org`) plus Caddy, which gets Let's Encrypt certificates automatically. Alternatively, Cloudflare Tunnel if you own a domain |
| E-mail | **Resend** free plan (3,000 e-mails a month): set `RESEND_API_KEY` in `dev.env`. Until you verify a sending domain in Resend, it only delivers to the e-mail address that owns the Resend account; other recipients are kept in `var/mail` with the reason. Brevo or a Gmail app password over SMTP also work |
| External model (optional) | Groq for phases A, C, E, F and G (no Ollama needed; the free tier is too small for full qualification, a paid key costs cents) |
| Code and images | GitHub (this repository) |

## 1. Create the server
1. Sign up at Oracle Cloud and create a **VM.Standard.A1.Flex** instance: Ubuntu 24.04, 4 OCPU, 24 GB.
2. In the instance's subnet security list, open TCP **80** and **443**. Keep 22 open for SSH. Do not open the internal ports (5441, 6391, 8700 and so on).
3. Also open 80 and 443 on the VM's own firewall:
   ```bash
   sudo iptables -I INPUT -p tcp -m multiport --dports 80,443 -j ACCEPT && sudo netfilter-persistent save
   ```
4. Install Docker and Git:
   ```bash
   curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker $USER
   ```

## 2. Get a name
At https://www.duckdns.org, create three subdomains pointing at the VM's public IP: `myapp`, `myapp-staff` and `myapp-auth` (`.duckdns.org`). Each portal and Keycloak gets its own address.

## 3. Configure and start
```bash
git clone https://github.com/adnan-mitul/assureops-ai.git && cd assureops-ai
python3 scripts/init_dev_env.py      # generates fresh secrets into infra/compose/dev.env (never commit it)
```
Add the public addresses and mail settings to `infra/compose/dev.env`:
```
PUBLIC_CUSTOMER_ORIGIN=https://myapp.duckdns.org
PUBLIC_STAFF_ORIGIN=https://myapp-staff.duckdns.org
PUBLIC_AUTH_ORIGIN=https://myapp-auth.duckdns.org
CUSTOMER_OIDC_ISSUER=https://myapp-auth.duckdns.org/realms/assureops
STAFF_OIDC_ISSUER=https://myapp-auth.duckdns.org/realms/assureops-staff
STAFF_MFA_REQUIRED=true
RESEND_API_KEY=<your Resend key>
NOTIFY_FROM=AssureOps <no-reply@your-verified-domain>
ASSUREOPS_SEED_APPS=false
```
Then render the realms and portal settings, and start the stack:
```bash
python3 scripts/render_realm.py && python3 scripts/render_storage.py && python3 scripts/render_web_env.py
bash scripts/docker_up.sh
```
The first start builds the images and downloads the models (about 15–30 minutes).

## 4. HTTPS in front (Caddy)
Create `Caddyfile`:
```
myapp.duckdns.org        { reverse_proxy 127.0.0.1:3700 }
myapp-staff.duckdns.org  { reverse_proxy 127.0.0.1:3710 }
myapp-auth.duckdns.org   { reverse_proxy 127.0.0.1:8780 }
```
Then run:
```bash
docker run -d --name caddy --network host --restart unless-stopped -v $PWD/Caddyfile:/etc/caddy/Caddyfile -v caddy_data:/data caddy:2.8.4
```
Caddy obtains the certificates itself. Open https://myapp.duckdns.org.

Only the portals and Keycloak are public. The API is not exposed: browsers reach it through each portal's own server side.

If customers' CI pipelines should call the release gate, also add `myapp-api.duckdns.org { reverse_proxy 127.0.0.1:8700 }` and give them that address as `ASSUREOPS_API_URL`.

Keycloak keeps its accounts in the `kcdata` volume. Never delete that volume on a running deployment: registered customers would lose their logins.

## 5. Updates
```bash
cd assureops-ai && git pull && bash scripts/docker_up.sh
```
The pipeline's signed images and the `DEPLOY_ENDPOINT` deploy jobs (see the operator guide) are for a hosting platform with a deployment API. On a single free VM, `git pull` plus `docker_up.sh` is the update path.

## Limits of the free setup
- One VM, no backups by default. Copy `pg_dump` output and the object store elsewhere regularly (`scripts/backup_restore_check.py` shows the procedure).
- CPU models are slow: an AI phase takes minutes.
- Oracle may reclaim Always Free instances that stay idle for a long time.
- Fine for a demo or pilot, not for production customers.
