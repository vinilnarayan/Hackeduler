# Hosting on AWS: EC2 + RDS + SES

This branch (`aws/ec2-rds-ses`) runs Hackeduler in Docker on an **EC2** machine, with its database on **Amazon RDS
(PostgreSQL 16)** and its email sent through **Amazon SES** and/or an SMTP server. The local-server branch is
unchanged and keeps working on its own.

```
 users ──HTTPS──> AWS load balancer (or host proxy) ──HTTP──> EC2: frontend :7080 ─> backend ─> RDS (TLS, port 5432)
                                                             worker ─────────────────────────> Amazon SES (API, IAM role)
                         other apps on the same EC2 (e.g. SPARK) use their own ports ─────────> own compose project
```

## 1. What changed compared with the local setup

| Area | Local branch | AWS branch |
|---|---|---|
| Database | `db` container + Docker volume | **Amazon RDS**; no `db` container, no volume. `HACKEDULER_DB_*` in `.env`; TLS verified with the RDS CA bundle |
| Backups | `backup` container writing to `./backups` | RDS automated backups + snapshots; `deploy.sh` also dumps to `./backups` before every deploy; `scripts/backup-db.sh` on demand |
| Email | SMTP only | **SES (AWS API)** and/or **SMTP**, optional automatic fallback, chosen in **Admin → Settings**; test buttons there |
| Ports | 8080 / 443 / 80 | **7080 / 7443 / 7081** - nothing on 80/443/8080, so SPARK and others are undisturbed |
| Shared host | - | fixed compose project name, memory/CPU limits, log rotation; `deploy.sh` touches only this project |
| HTTPS | built-in Caddy front | recommended: an **AWS load balancer** (`--public-url`); the Caddy front is still available |

## 2. One-time AWS setup

### 2.1 RDS
1. Create an **RDS for PostgreSQL 16** instance (single-AZ is fine for an internal tool; Multi-AZ if your policy asks),
   in private subnets, **encryption on**, **automated backups** (7-14 days), **deletion protection on**.
2. Security group of the database: allow **TCP 5432 only from the EC2 instance's security group**.
3. Create the database and an application user that **owns** it (migrations create and alter tables; no superuser and no
   extensions are needed). As the RDS master user:
   ```sql
   CREATE ROLE hackeduler LOGIN PASSWORD '<strong password>';
   CREATE DATABASE hackeduler OWNER hackeduler;
   ```
   RDS passwords may not contain `/`, `@`, `"` or spaces; `$ & # ;` are fine because `.env` single-quotes the value. Avoid a
   single quote in the password.

### 2.2 EC2
1. A Linux instance with Docker and the Compose plugin (e.g. Amazon Linux 2023 or Ubuntu), enough for both apps (start
   with 2 vCPU / 4 GB if SPARK is there too). Outbound HTTPS must work (package installs, the RDS CA download, Microsoft
   Entra for SSO, SES).
2. Security group: allow the app port (**7080**) **only from the load balancer's security group** (or your office/VPN range).
3. **Instance role** (for SES, no passwords): attach a role with
   ```json
   { "Version": "2012-10-17", "Statement": [{ "Effect": "Allow", "Action": "ses:SendEmail",
     "Resource": ["arn:aws:ses:<region>:<account-id>:identity/<your-domain-or-address>",
                  "arn:aws:ses:<region>:<account-id>:configuration-set/<name-if-used>"] }] }
   ```
4. **Containers need to reach the instance role.** Set the instance metadata hop limit to 2, otherwise Docker
   containers cannot get credentials (symptom: SES errors about missing credentials):
   `aws ec2 modify-instance-metadata-options --instance-id <id> --http-put-response-hop-limit 2 --http-tokens required`

### 2.3 SES
Verify the sender (the **Sender address** in Admin → Settings) or its domain in SES in the chosen region, and request
**production access** (a new account is in the "sandbox" and can only send to verified addresses). Add SPF/DKIM for the
domain so mail is not marked as spam.

### 2.4 Load balancer and DNS (recommended)
Application Load Balancer with an **ACM certificate** for the app's DNS name, a listener on 443, and a target group
pointing to the EC2 instance on port **7080** (health check path `/api/health`). With one ALB for several apps use
**host-based rules** (e.g. `hackeduler.example.com` -> port 7080, the SPARK name -> its own port). Point the DNS name at
the ALB. Then deploy with `--public-url https://hackeduler.example.com`.

No load balancer? Use the built-in front instead: `./deploy.sh --domain <name> --https files` (company certificate in
`certs/`) or `--https auto` (Let's Encrypt, needs public ports 80/443 - not possible when SPARK already uses them).

## 3. Deploying

```bash
git clone <repo> && cd hackeduler/hackeduler && git checkout aws/ec2-rds-ses
./deploy.sh                      # first run: creates .env with random secrets, then stops
nano .env                        # HACKEDULER_DB_HOST / _NAME / _USER / _PASSWORD='...' ; HACKEDULER_AWS_REGION ; sender etc.
./deploy.sh --public-url https://hackeduler.example.com
```

`deploy.sh` then downloads the RDS CA bundle, checks it can connect, backs up (if the database already has data),
builds, starts, waits for health and creates the first administrator (password printed once). Later upgrades are just
`git pull && ./deploy.sh`.

After the first successful start set `HACKEDULER_SEED=none` in `.env`: with `minimal` the start-up seed re-adds default
activity types, templates and settings that are missing.

## 4. Email: SES and SMTP

Admin → **Settings → Email notifications → Mail service**:

* **Primary** and **Fallback** service: *Amazon SES* or *SMTP server* (fallback may be "No fallback"). If the primary fails
  (rejected, network, authentication), the same email is tried on the fallback straight away; only if both fail does it
  count as a failed attempt and retry later with the usual back-off. **Admin → Email & Templates → delivery log** shows
  which service delivered each email ("Sent via").
* **SES**: region (e.g. `ap-south-1`) and an optional configuration set. Credentials = the EC2 instance role.
* **SMTP**: host, port, username here; the password only in `.env` (`HACKEDULER_SMTP_PASSWORD`). Works for a corporate
  relay or the SES SMTP endpoint (`email-smtp.<region>.amazonaws.com`, port 587, STARTTLS).
* **Send a test email**: *Test current setup*, *Test SES only*, *Test SMTP only*. Save settings first; the test uses the
  saved values and shows the provider's error message if it fails.
* Environment defaults (used until the admin overrides them): `HACKEDULER_EMAIL_PRIMARY`, `HACKEDULER_EMAIL_FALLBACK`,
  `HACKEDULER_AWS_REGION`, `HACKEDULER_SES_CONFIGURATION_SET`, `HACKEDULER_SMTP_*`.

Common SES errors: `MessageRejected ... not verified` (verify the sender / the recipient in the sandbox), `AccessDenied`
(instance role policy, or the resource ARN does not match the region), "Unable to locate credentials" (metadata hop
limit, see 2.2), `NoRegionError` (set the region).

## 5. Sharing the machine with SPARK (or other apps)

* Hackeduler never publishes 80, 443 or 8080. Its ports are `HACKEDULER_HTTP_PORT` (7080), `HACKEDULER_HTTPS_PORT` (7443)
  and `HACKEDULER_HTTP_REDIRECT_PORT` (7081). `./deploy.sh` stops with a suggestion if one of them is taken.
* The compose project is named `hackeduler`, so its containers (`hackeduler-backend-1`, ...), network and images are
  separate from other projects. `deploy.sh` never runs `docker system prune`, `down -v` or `--remove-orphans`.
* Memory/CPU limits (`HACKEDULER_BACKEND_MEM`, `..._CPUS`, `HACKEDULER_WORKER_MEM`, ...) and log rotation (10 MB x 5 per
  container) keep Hackeduler from starving or filling the disk for its neighbours. Raise the limits if it is slow.
* Database connections: each web worker holds up to `DB_POOL_SIZE + DB_MAX_OVERFLOW` (default 10) connections;
  with 2 web workers plus the worker that is roughly 30. Keep the total below the `max_connections` of the RDS instance
  class (a t3.micro allows ~80) shared with any other application that uses the same RDS instance.
* If a reverse proxy on the host fronts several apps, run `./deploy.sh --bind 127.0.0.1 --port 7080` and proxy the DNS
  name to `127.0.0.1:7080` (see `NETWORK.md` §4).

## 6. Moving the data from the local server to RDS (one time)

Do this in a quiet moment; the old server stays untouched as the rollback.

1. **On the old server**, stop writes and take the final backup:
   ```bash
   docker compose stop backend worker
   ./deploy.sh      # (or ./scripts/backup-db.sh on the old branch) - note the resulting backups/*.dump
   ```
   Also copy its **`.env`** values `HACKEDULER_SECRET_KEY` and **`HACKEDULER_ENCRYPTION_KEY`** - they must be **identical** on
   AWS: the SSO client secret in the database is encrypted with the encryption key, and a different key breaks SSO until the
   secret is re-entered.
2. **On EC2**, run `./deploy.sh` once as in section 3 so the database user, network path and CA are verified (the empty
   database gets its tables), then stop the app: `docker compose stop backend worker`.
3. Copy the dump to EC2 (`scp`) and restore it **into RDS**:
   ```bash
   ./scripts/restore-db.sh /path/to/hackeduler-YYYYMMDD.dump     # type "restore" to confirm
   ```
   Original owners and grants in the dump are ignored (`--no-owner --no-privileges`), so the RDS user owns everything.
4. `./deploy.sh` again: it backs up, applies any newer migrations (e.g. 0011 resource role, 0012 email provider - they only
   add columns), starts and checks health.
5. **Verify**: sign in, compare counts (bookings, users) with the old server, open a booking, send a test email from
   Admin → Settings.
6. **Switch**: point the DNS name at the ALB; update Entra (redirect URI `https://<name>/api/auth/sso/<slug>/callback`) and
   Admin → Single Sign-On → **Public URL**; users sign in again (sessions do not carry over).
7. Keep the old server (stopped) for a few days, then retire it.

**Rollback:** point DNS back and `docker compose start backend worker` on the old server - its database was never changed.

## 7. Operations cheat sheet

| Task | Command |
|---|---|
| Upgrade | `git pull && ./deploy.sh` |
| Logs | `docker compose logs -f backend worker` |
| Health | `curl -s http://localhost:7080/api/health` |
| Manual backup | `./scripts/backup-db.sh` |
| Restore | `./scripts/restore-db.sh backups/<file>.dump` (or restore an RDS snapshot / point in time) |
| New admin | `docker compose exec backend python -m app.manage create-admin you@example.com` |
| Break-glass login | `HACKEDULER_FORCE_LOCAL_LOGIN=true` in `.env`, then `./deploy.sh` |
