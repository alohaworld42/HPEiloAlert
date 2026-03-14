# HPE iLO Alert — Future Plan

## 1. Richer Alert Emails
- Include full stats from the last polling interval in every alert email:
  - All fan speeds (not just the ones over threshold)
  - All temperature readings (CPU, ambient, memory, etc.)
  - Any errors encountered during the interval (connection failures, timeouts)
  - Health status summary (OK / Warning / Critical counts)
- Show trends: e.g. "Fan 1 went from 42% → 78% in the last 10 minutes"
- Include a mini table of recent history in the email body

## 2. Slack Integration
- Send alerts to a Slack channel in addition to (or instead of) email
- Use Slack Incoming Webhook (no bot token / app registration needed)
- Config via `.env`:
  ```
  SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T.../B.../xxx
  SLACK_CHANNEL=#infra-alerts
  ```
- Rich formatting with Slack Block Kit (colour-coded, fan table, etc.)
- Same alert logic: new alert, repeat, recovery

## 3. DKIM Setup for Cross-Domain Email Delivery
- Enable `DKIM_AUTOGENERATE=true` on the Postfix container
- Extract the generated DKIM public key
- Add DNS records to `vanderslotai.com`:
  - `TXT` record for DKIM key
  - `TXT` record for SPF: `v=spf1 ip4:<server-ip> ~all`
- This allows emails to be accepted by Gmail, Outlook, and other strict providers
- Without this, emails to external domains (gmail.com, etc.) will bounce or land in spam

## Priority
1. DKIM + SPF (unblocks email delivery to all recipients)
2. Richer alert emails (most value for daily operations)
3. Slack integration (nice-to-have, reduces email noise)
