# HPE iLO Fan Speed Alert

Monitors HPE iLO fan speeds and temperatures via the Redfish API and sends email alerts when any fan exceeds a configurable threshold. Includes a live web dashboard. Runs as Docker containers — no other dependencies required.

## Features

- Polls iLO Redfish API on a configurable interval
- Sends an **alert email** when a fan crosses the threshold
- Sends a **recovery email** when fans drop back to normal
- **Repeat alerts** while fans stay above threshold (configurable interval)
- Edge-triggered: only one email per event, not every check
- HTML + plain text email with colour-coded fan table
- **Web dashboard** with live fan speed and temperature graphs
- Built-in **Postfix** container for direct email delivery (no signup needed)
- Pure Python stdlib — tiny Alpine image (~50MB)

## Requirements

- Docker with Compose plugin
- Network access from the host to your iLO management IP

## Quick Start

```bash
# 1. Clone
git clone https://github.com/alohaworld42/HPEiloAlert.git
cd HPEiloAlert

# 2. Configure
cp .env.example .env
nano .env          # fill in your iLO IP, credentials, and email settings

# 3. Build and run
docker compose up -d --build

# 4. Check logs
docker compose logs -f
```

## Dashboard

A built-in web dashboard shows live fan speeds and temperatures with history graphs.

- **URL:** `http://<docker-host>:8181`
- Auto-refreshes every poll interval
- Shows fan speed and temperature history charts (last 60 polls)
- Displays current readings with health status

If accessing from a remote machine, use an SSH tunnel:

```bash
ssh -L 8181:localhost:8181 user@<docker-host-ip> -N
```

Then open `http://localhost:8181` in your browser.

## Configuration

All settings are in `.env` (copied from `.env.example`):

| Variable | Description | Default |
|---|---|---|
| `ILO_HOST` | iLO IP or hostname | required |
| `ILO_USERNAME` | iLO username | required |
| `ILO_PASSWORD` | iLO password | required |
| `ILO_VERIFY_SSL` | Verify iLO SSL cert | `false` |
| `ALERT_THRESHOLD` | Fan speed % to trigger alert | `70` |
| `ALERT_SERVER_NAME` | Friendly name in emails/dashboard | `HPE Server` |
| `ALERT_INTERVAL_SEC` | Seconds between checks | `120` |
| `ALERT_REPEAT_SEC` | Re-send alert while fans stay over threshold | `300` |
| `WEB_PORT` | Dashboard port inside the container | `8080` |
| `SMTP_HOST` | SMTP server hostname | `postfix` |
| `SMTP_PORT` | SMTP port | `25` |
| `SMTP_TLS` | Use STARTTLS | `false` |
| `SMTP_USERNAME` | SMTP auth username | (empty) |
| `SMTP_PASSWORD` | SMTP auth password | (empty) |
| `EMAIL_FROM` | Sender address | required |
| `EMAIL_TO` | Recipient(s), comma-separated | required |
| `MAIL_DOMAIN` | Domain for outgoing emails (Postfix) | `localhost` |

### Email Setup

**Option A — Local Postfix (default, no signup):**
Emails are sent directly via MX records using the included Postfix container. No external account needed. Set `MAIL_DOMAIN` to your domain so emails aren't flagged as spam.

**Option B — External SMTP:**
Use any SMTP provider (Brevo, Mailjet, Gmail, etc.). Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS`, `SMTP_USERNAME`, and `SMTP_PASSWORD` in your `.env`.

## Useful Commands

```bash
# Start
docker compose up -d --build

# Stop
docker compose down

# View live logs
docker compose logs -f

# View only alert logs
docker compose logs -f ilo-fan-alert

# View postfix delivery logs
docker compose logs postfix

# Restart after .env change
docker compose down && docker compose up -d --build
```

## Security Notes

- `.env` is listed in `.gitignore` — never commit it
- iLO uses a self-signed cert by default; `ILO_VERIFY_SSL=false` skips verification for internal use
- Use an app password or dedicated SMTP account for `SMTP_PASSWORD`
- The dashboard has no authentication — use SSH tunnels or a reverse proxy to restrict access

## Tested On

- HPE ProLiant DL385 Gen11 with iLO 6
- Ubuntu 22.04 / 24.04
