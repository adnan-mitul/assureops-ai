# Hosting AssureOps on a laptop with Cloudflare Tunnel

A Windows laptop runs the whole platform in Docker. Cloudflare Tunnel publishes it on your own domain over HTTPS, with no open ports and no public IP. The tunnel and the domain on Cloudflare's free plan cost nothing; only the domain itself costs money, unless you get it free (for example through the GitHub Student Developer Pack).

## What the laptop needs
- Windows 10/11, **16 GB RAM** at least (32 GB is comfortable), about **60 GB** free SSD space.
- **Plugged in** and on a stable internet connection.
- Installed:
  - Docker Desktop (WSL 2);
  - Git for Windows (gives Git Bash);
  - Python 3.12 (python.org; tick "Add to PATH").

## 1. Get the code and configure it
In Git Bash:
```bash
git clone https://github.com/adnan-mitul/assureops-ai.git && cd assureops-ai
python scripts/init_dev_env.py
python scripts/deploy/public_domain.py --domain yourdomain.com
```
This creates fresh secrets and sets the three public addresses: `app.`, `staff.` and `auth.yourdomain.com`.

Open `infra/compose/dev.env` and add your mail key:
```
RESEND_API_KEY=<your Resend key>
```
Then start everything (the first run takes 15–30 minutes):
```bash
bash scripts/docker_up.sh
```

## 2. Publish it with Cloudflare Tunnel
1. Create a free Cloudflare account and **add your domain**. At your domain registrar, change the nameservers to the two Cloudflare gives you, then wait until Cloudflare shows the domain as active.
2. Open **Cloudflare Zero Trust → Networks → Tunnels → Create a tunnel**, choose **Cloudflared**, and name it `assureops`.
3. Choose **Windows**. Cloudflare shows a command like `cloudflared.exe service install <token>`. Run it in an **Administrator** PowerShell; it installs the connector as a Windows service.
4. Under the tunnel's **Public hostnames**, add:

   | Hostname | Service |
   |---|---|
   | `app.yourdomain.com` | `http://localhost:3700` |
   | `staff.yourdomain.com` | `http://localhost:3710` |
   | `auth.yourdomain.com` | `http://localhost:8780` |
   | `api.yourdomain.com` (optional, for customers' CI release gates) | `http://localhost:8700` |

5. Open `https://app.yourdomain.com`.

## 3. Keep it running
1. **Docker Desktop → Settings → General:** tick *Start Docker Desktop when you sign in*.
2. **Settings → System → Power:** when plugged in, *never* sleep or hibernate.
3. **Control Panel → Power Options → Choose what closing the lid does:** *Do nothing* when plugged in. The lid can then stay closed.
4. **Windows Update → Advanced options → Active hours:** set them so updates restart the laptop at night.
5. Every container restarts on its own, and the Cloudflare connector is a Windows service. After a restart, the site comes back once **someone signs in to Windows**: Docker Desktop only starts with a user session.

### What happens when the laptop is shut down or loses power
- The site is offline. Visitors see a Cloudflare error page (the tunnel has nothing to reach).
- **No data is lost.** Database, files, accounts and reports live in Docker volumes on the disk.
- An assessment that was running stops. Its unfinished steps are retried or marked unverified, never passed.
- E-mails not yet sent go out after the restart.
- Switch it on and sign in: Docker starts, the containers come back, the tunnel reconnects, and the site is back in about 2–5 minutes.

## Updates and backups
```bash
cd assureops-ai && git pull && bash scripts/docker_up.sh
```
Back up regularly; a laptop disk is a single copy. `scripts/backup_restore_check.py` shows the database and object-store procedure. Keep `infra/compose/dev.env` safe and private: it holds the secrets.

## If you change the domain later
```bash
python scripts/deploy/public_domain.py --domain newdomain.com --reset-identity && bash scripts/docker_up.sh
```
`--reset-identity` re-imports the sign-in realms with the new addresses. Accounts registered on the old address are reset.
