# HPE iLO Fan Speed Alert

Monitors HPE iLO fan speeds via the Redfish API and sends an email alert when any fan exceeds a configurable threshold. Runs as a Docker container — no other dependencies required.

## Features

- Polls iLO Redfish API on a configurable interval
- Sends an **alert email** when a fan crosses the threshold
- Sends a **recovery email** when fans drop back to normal
- Edge-triggered: only one email per event, not every check
- HTML + plain text email with colour-coded fan table
- Pure Python stdlib — tiny Alpine image (~50MB)

## Requirements

- Docker with Compose plugin
- Network access from the host to your iLO management IP
- An SMTP server to send alerts

## Quick Start

```bash
# 1. Clone
git clone https://github.com/yourorg/ilo-fan-alert.git
cd ilo-fan-alert

# 2. Configure
cp .env.example .env
nano .env          # fill in your iLO IP, credentials, and SMTP settings

# 3. Build and run
docker compose up -d

# 4. Check logs
docker compose logs -f
```

## Configuration

All settings are in `.env` (copied from `.env.example`):

| Variable | Description | Default |
|---|---|---|
| `ILO_HOST` | iLO IP or hostname | required |
| `ILO_USERNAME` | iLO username | required |
| `ILO_PASSWORD` | iLO password | required |
| `ILO_VERIFY_SSL` | Verify iLO SSL cert | `false` |
| `ALERT_THRESHOLD` | Fan speed % to trigger alert | `70` |
| `ALERT_SERVER_NAME` | Friendly name in emails | `HPE Server` |
| `ALERT_INTERVAL_SEC` | Seconds between checks | `120` |
| `SMTP_HOST` | SMTP server hostname | required |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_TLS` | Use STARTTLS | `true` |
| `SMTP_USERNAME` | SMTP auth username | optional |
| `SMTP_PASSWORD` | SMTP auth password | optional |
| `EMAIL_FROM` | Sender address | required |
| `EMAIL_TO` | Recipient(s), comma-separated | required |

## Useful Commands

```bash
# Start
docker compose up -d

# Stop
docker compose down

# View live logs
docker compose logs -f

# Restart after .env change
docker compose down && docker compose up -d

# Rebuild after code change
docker compose up -d --build
```

## Security Notes

- `.env` is listed in `.gitignore` — never commit it
- iLO uses a self-signed cert by default; `ILO_VERIFY_SSL=false` skips verification for internal use
- Use an app password or dedicated SMTP account for `SMTP_PASSWORD`

## Tested On

- HPE ProLiant DL385 Gen11 with iLO 6
- Ubuntu 22.04 / 24.04
