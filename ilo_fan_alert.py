#!/usr/bin/env python3
"""
HPE iLO Fan Speed Alert — Docker Edition
Reads all config from environment variables and runs in a loop.
Deploy via docker-compose, no cron needed.
"""

import json
import os
import smtplib
import ssl
import time
import urllib.request
import urllib.error
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ─────────────────────────────────────────────
#  CONFIG FROM ENVIRONMENT
# ─────────────────────────────────────────────

ILO = {
    "host":       os.environ["ILO_HOST"],
    "username":   os.environ["ILO_USERNAME"],
    "password":   os.environ["ILO_PASSWORD"],
    "verify_ssl": os.getenv("ILO_VERIFY_SSL", "false").lower() == "true",
}

ALERT = {
    "threshold":    int(os.getenv("ALERT_THRESHOLD", "70")),
    "server_name":  os.getenv("ALERT_SERVER_NAME", "HPE Server"),
    "interval_sec": int(os.getenv("ALERT_INTERVAL_SEC", "120")),
}

EMAIL = {
    "smtp_host": os.environ["SMTP_HOST"],
    "smtp_port": int(os.getenv("SMTP_PORT", "587")),
    "use_tls":   os.getenv("SMTP_TLS", "true").lower() == "true",
    "username":  os.getenv("SMTP_USERNAME", ""),
    "password":  os.getenv("SMTP_PASSWORD", ""),
    "from_addr": os.environ["EMAIL_FROM"],
    "to_addrs":  [a.strip() for a in os.environ["EMAIL_TO"].split(",")],
}

# ─────────────────────────────────────────────
#  STATE  (cooldown — only alert once per event)
# ─────────────────────────────────────────────

alert_state: set = set()

# ─────────────────────────────────────────────
#  CORE FUNCTIONS
# ─────────────────────────────────────────────

def fetch_fan_data():
    import base64
    url = f"https://{ILO['host']}/redfish/v1/Chassis/1/Thermal"
    credentials = base64.b64encode(
        f"{ILO['username']}:{ILO['password']}".encode()
    ).decode()

    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Accept", "application/json")

    ctx = ssl.create_default_context()
    if not ILO["verify_ssl"]:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        return json.loads(resp.read().decode())


def check_fans(data):
    over, under = [], []
    for fan in data.get("Fans", []):
        name   = fan.get("Name", "Unknown Fan")
        speed  = fan.get("Reading")
        status = fan.get("Status", {}).get("Health", "Unknown")

        if speed is None:
            continue

        entry = {"name": name, "speed": speed, "status": status}
        if speed > ALERT["threshold"]:
            over.append(entry)
        else:
            under.append(entry)

    return over, under


def build_email(subject, alerts, all_fans, is_recovery=False):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    accent    = "#16a34a" if is_recovery else "#dc2626"
    icon      = "✅" if is_recovery else "⚠️"
    heading   = "Fan Speed Recovered" if is_recovery else "Fan Speed Alert"

    alert_rows = "".join(
        f"<tr style='background:{'#dcfce7' if is_recovery else '#fff3cd'}'>"
        f"<td padding='8px'>{icon} {f['name']}</td>"
        f"<td style='text-align:center;font-weight:bold;color:{accent}'>{f['speed']}%</td>"
        f"<td>{f['status']}</td></tr>"
        for f in alerts
    )

    all_rows = ""
    for f in all_fans:
        speed  = f.get("Reading", "N/A")
        name   = f.get("Name", "Unknown")
        health = f.get("Status", {}).get("Health", "Unknown")
        over   = isinstance(speed, int) and speed > ALERT["threshold"]
        bg     = "background:#fff3cd" if over else ""
        tick   = "⚠" if over else "✓"
        all_rows += (
            f"<tr style='{bg}'><td>{tick} {name}</td>"
            f"<td style='text-align:center'>{speed}%</td>"
            f"<td>{health}</td></tr>"
        )

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;max-width:640px">
      <h2 style="color:{accent}">{icon} {heading}</h2>
      <table style="border-collapse:collapse;width:100%;margin-bottom:16px">
        <tr><td><b>Server</b></td><td>{ALERT['server_name']}</td></tr>
        <tr><td><b>Time</b></td><td>{timestamp}</td></tr>
        <tr><td><b>Threshold</b></td><td>{ALERT['threshold']}%</td></tr>
        <tr><td><b>Fans affected</b></td>
            <td style="color:{accent}"><b>{len(alerts)}</b></td></tr>
      </table>

      <h3 style="color:{accent}">{'Recovered Fans' if is_recovery else 'Fans Above Threshold'}</h3>
      <table style="border-collapse:collapse;width:100%;border:1px solid #ddd">
        <thead style="background:{'#16a34a' if is_recovery else '#f97316'};color:white">
          <tr><th style="padding:8px;text-align:left">Fan</th>
              <th style="padding:8px">Speed</th>
              <th style="padding:8px">Health</th></tr>
        </thead>
        <tbody>{alert_rows}</tbody>
      </table>

      <h3 style="margin-top:24px">All Fans</h3>
      <table style="border-collapse:collapse;width:100%;border:1px solid #ddd;font-size:13px">
        <thead style="background:#374151;color:white">
          <tr><th style="padding:6px;text-align:left">Fan</th>
              <th style="padding:6px">Speed</th>
              <th style="padding:6px">Health</th></tr>
        </thead>
        <tbody>{all_rows}</tbody>
      </table>

      <p style="margin-top:24px;font-size:12px;color:#888">
        HPE iLO Fan Alert · {ILO['host']} · checked every {ALERT['interval_sec']}s
      </p>
    </body></html>
    """

    plain = (
        f"{heading} — {ALERT['server_name']}\n"
        f"Time:      {timestamp}\n"
        f"Threshold: {ALERT['threshold']}%\n\n"
        + "\n".join(f"  {f['name']}: {f['speed']}%" for f in alerts)
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL["from_addr"]
    msg["To"]      = ", ".join(EMAIL["to_addrs"])
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    return msg


def send_email(msg):
    if EMAIL["use_tls"]:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(EMAIL["smtp_host"], EMAIL["smtp_port"]) as s:
            s.ehlo()
            s.starttls(context=ctx)
            if EMAIL["username"]:
                s.login(EMAIL["username"], EMAIL["password"])
            s.sendmail(EMAIL["from_addr"], EMAIL["to_addrs"], msg.as_string())
    else:
        with smtplib.SMTP(EMAIL["smtp_host"], EMAIL["smtp_port"]) as s:
            if EMAIL["username"]:
                s.login(EMAIL["username"], EMAIL["password"])
            s.sendmail(EMAIL["from_addr"], EMAIL["to_addrs"], msg.as_string())


def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────

def run():
    global alert_state

    log(f"Starting — monitoring {ALERT['server_name']} ({ILO['host']}) "
        f"every {ALERT['interval_sec']}s, threshold={ALERT['threshold']}%")

    while True:
        try:
            data         = fetch_fan_data()
            all_fans     = data.get("Fans", [])
            over_fans, _ = check_fans(data)
            over_names   = {f["name"] for f in over_fans}

            # Fans that newly crossed the threshold → send alert
            new_alerts = [f for f in over_fans if f["name"] not in alert_state]
            if new_alerts:
                log(f"ALERT — {len(new_alerts)} new fan(s) above {ALERT['threshold']}%")
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                subject   = (
                    f"[ALERT] {ALERT['server_name']} – "
                    f"{len(over_fans)} fan(s) above {ALERT['threshold']}% – {timestamp}"
                )
                msg = build_email(subject, over_fans, all_fans, is_recovery=False)
                send_email(msg)
                log(f"Alert email sent to {', '.join(EMAIL['to_addrs'])}")
                alert_state = over_names

            # Fans that dropped back below threshold → send recovery
            recovered = [name for name in alert_state if name not in over_names]
            if recovered and not over_names:
                log(f"RECOVERY — all fans back below {ALERT['threshold']}%")
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                subject   = (
                    f"[RECOVERY] {ALERT['server_name']} – "
                    f"fans back below {ALERT['threshold']}% – {timestamp}"
                )
                recovered_fans = [
                    {"name": n, "speed": "< threshold", "status": "OK"}
                    for n in recovered
                ]
                msg = build_email(subject, recovered_fans, all_fans, is_recovery=True)
                send_email(msg)
                log(f"Recovery email sent to {', '.join(EMAIL['to_addrs'])}")
                alert_state = set()

            if not new_alerts and not recovered:
                status = f"{len(over_fans)} above threshold" if over_fans else "all OK"
                log(f"Check complete — {status}")

        except urllib.error.URLError as e:
            log(f"ERROR: Cannot reach iLO at {ILO['host']} — {e.reason}")
        except Exception as e:
            log(f"ERROR: {e}")

        time.sleep(ALERT["interval_sec"])


if __name__ == "__main__":
    run()
