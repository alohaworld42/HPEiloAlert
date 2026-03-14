#!/usr/bin/env python3
"""
HPE iLO Fan Speed Alert — Docker Edition
Reads all config from environment variables and runs in a loop.
Deploy via docker-compose, no cron needed.
"""

import base64
import collections
import html
import http.server
import json
import os
import smtplib
import ssl
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid

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
    "repeat_sec":   int(os.getenv("ALERT_REPEAT_SEC", "300")),
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

WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

# ─────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────

alert_state: set = set()
last_alert_time: float = 0.0

_last_reading: dict = {"fans": [], "temps": [], "updated": None, "error": None}
_history: collections.deque = collections.deque(maxlen=60)  # last 60 polls
_reading_lock = threading.Lock()

# ─────────────────────────────────────────────
#  CORE FUNCTIONS
# ─────────────────────────────────────────────

def fetch_fan_data():
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
    msg["Subject"]    = subject
    msg["From"]       = EMAIL["from_addr"]
    msg["To"]         = ", ".join(EMAIL["to_addrs"])
    msg["Message-ID"] = make_msgid(domain=EMAIL["from_addr"].split("@")[-1])
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
#  DASHBOARD
# ─────────────────────────────────────────────

def _chart_datasets(history, key, names):
    palette = [
        "#3b82f6","#f97316","#10b981","#8b5cf6","#ef4444",
        "#06b6d4","#f59e0b","#ec4899","#14b8a6","#6366f1",
    ]
    datasets = []
    for i, name in enumerate(names):
        colour = palette[i % len(palette)]
        datasets.append({
            "label": name,
            "data": [pt[key].get(name) for pt in history],
            "borderColor": colour,
            "backgroundColor": colour + "22",
            "borderWidth": 2,
            "pointRadius": 2,
            "tension": 0.3,
            "fill": False,
        })
    return datasets


def build_dashboard_html():
    with _reading_lock:
        fans    = _last_reading["fans"]
        temps   = _last_reading["temps"]
        updated = _last_reading["updated"]
        error   = _last_reading["error"]
        history = list(_history)

    # ── chart data ──────────────────────────────
    labels     = [pt["ts"] for pt in history]
    fan_names  = list(dict.fromkeys(n for pt in history for n in pt["fans"]))
    temp_names = list(dict.fromkeys(n for pt in history for n in pt["temps"]))
    fan_ds     = _chart_datasets(history, "fans",  fan_names)
    temp_ds    = _chart_datasets(history, "temps", temp_names)
    chart_data = json.dumps({"labels": labels, "fan_ds": fan_ds, "temp_ds": temp_ds})

    # ── table rows ──────────────────────────────
    fan_rows = ""
    for f in fans:
        speed  = f.get("Reading", "N/A")
        name   = f.get("Name", "Unknown")
        health = f.get("Status", {}).get("Health", "Unknown")
        units  = f.get("ReadingUnits", "%")
        over   = isinstance(speed, (int, float)) and speed > ALERT["threshold"]
        bg     = "#fff3cd" if over else "#f0fdf4"
        badge  = (f'<span style="color:#dc2626;font-weight:bold">⚠ {speed}{units}</span>'
                  if over else f'<span style="color:#16a34a">{speed}{units}</span>')
        fan_rows += (
            f"<tr style='background:{bg}'>"
            f"<td style='padding:8px'>{name}</td>"
            f"<td style='padding:8px;text-align:center'>{badge}</td>"
            f"<td style='padding:8px;text-align:center'>{health}</td></tr>"
        )

    temp_rows = ""
    for t in temps:
        reading = t.get("ReadingCelsius", "N/A")
        name    = t.get("Name", "Unknown")
        context = t.get("PhysicalContext", "")
        health  = t.get("Status", {}).get("Health", "Unknown")
        upper   = t.get("UpperThresholdCritical") or t.get("UpperThresholdNonCritical")
        hot     = isinstance(reading, (int, float)) and isinstance(upper, (int, float)) and reading >= upper * 0.9
        bg      = "#fff3cd" if hot else ""
        temp_rows += (
            f"<tr style='background:{bg}'>"
            f"<td style='padding:8px'>{name}</td>"
            f"<td style='padding:8px;color:#6b7280;font-size:12px'>{context}</td>"
            f"<td style='padding:8px;text-align:center'>{reading} °C</td>"
            f"<td style='padding:8px;text-align:center'>{health}</td></tr>"
        )

    status_bar = ""
    if error:
        status_bar = f'<div style="background:#fee2e2;color:#991b1b;padding:10px 16px;border-radius:6px;margin-bottom:16px">⚠ Last poll failed: {html.escape(str(error))}</div>'
    elif not updated:
        status_bar = '<div style="background:#fef9c3;padding:10px 16px;border-radius:6px;margin-bottom:16px">Waiting for first reading…</div>'

    no_history = '<p style="color:#9ca3af;font-size:13px">No history yet — waiting for first poll.</p>'

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="{ALERT['interval_sec']}">
  <title>{ALERT['server_name']} — iLO Monitor</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <style>
    body  {{ font-family: Arial, sans-serif; color: #1f2937; max-width: 960px;
            margin: 0 auto; padding: 24px; background: #f9fafb; }}
    h1    {{ font-size: 20px; margin-bottom: 4px; }}
    h2    {{ font-size: 15px; margin: 28px 0 8px; color: #374151; }}
    .meta {{ font-size: 13px; color: #6b7280; margin-bottom: 20px; }}
    .card {{ background:#fff; border:1px solid #e5e7eb; border-radius:8px;
             padding:16px; margin-bottom:8px; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff;
             border: 1px solid #e5e7eb; border-radius: 6px; overflow: hidden; }}
    thead {{ background: #374151; color: #fff; }}
    th, td {{ padding: 0; }}
    th {{ padding: 8px 10px; text-align: left; font-size: 13px; }}
    tr:not(:last-child) td {{ border-bottom: 1px solid #e5e7eb; }}
  </style>
</head>
<body>
  <h1>🖥 {ALERT['server_name']}</h1>
  <div class="meta">
    {ILO['host']} &nbsp;·&nbsp; threshold {ALERT['threshold']}% &nbsp;·&nbsp;
    refreshes every {ALERT['interval_sec']}s &nbsp;·&nbsp;
    last updated: {updated or '—'}
  </div>
  {status_bar}

  <h2>Fan Speed History</h2>
  {'<div class="card"><canvas id="fanChart" height="120"></canvas></div>' if history else no_history}

  <h2>Temperature History</h2>
  {'<div class="card"><canvas id="tempChart" height="120"></canvas></div>' if history else no_history}

  <h2>Fans — current</h2>
  <table>
    <thead><tr><th>Name</th><th>Speed</th><th>Health</th></tr></thead>
    <tbody>{fan_rows or '<tr><td colspan="3" style="padding:12px;color:#9ca3af">No data yet</td></tr>'}</tbody>
  </table>

  <h2>Temperatures — current</h2>
  <table>
    <thead><tr><th>Sensor</th><th>Context</th><th>Reading</th><th>Health</th></tr></thead>
    <tbody>{temp_rows or '<tr><td colspan="4" style="padding:12px;color:#9ca3af">No data yet</td></tr>'}</tbody>
  </table>

  <script>
  (function() {{
    var d = {chart_data};
    if (!d.labels.length) return;
    var common = {{
      responsive: true,
      plugins: {{ legend: {{ position: "bottom", labels: {{ boxWidth: 12, font: {{ size: 11 }} }} }} }},
      scales: {{ x: {{ ticks: {{ maxTicksLimit: 10, font: {{ size: 10 }} }} }},
                 y: {{ beginAtZero: false }} }}
    }};
    new Chart(document.getElementById("fanChart"), {{
      type: "line",
      data: {{ labels: d.labels, datasets: d.fan_ds }},
      options: Object.assign({{}}, common, {{
        scales: Object.assign({{}}, common.scales, {{
          y: {{ title: {{ display: true, text: "Speed (%)" }}, beginAtZero: true, max: 100 }}
        }})
      }})
    }});
    new Chart(document.getElementById("tempChart"), {{
      type: "line",
      data: {{ labels: d.labels, datasets: d.temp_ds }},
      options: Object.assign({{}}, common, {{
        scales: Object.assign({{}}, common.scales, {{
          y: {{ title: {{ display: true, text: "Temperature (°C)" }}, beginAtZero: false }}
        }})
      }})
    }});
  }})();
  </script>
</body>
</html>"""


class _DashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = build_dashboard_html().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass  # suppress per-request access logs


def start_dashboard():
    server = http.server.ThreadingHTTPServer(("", WEB_PORT), _DashboardHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    log(f"Dashboard available at http://localhost:{WEB_PORT}")


# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────

def run():
    global alert_state, last_alert_time

    log(f"Starting — monitoring {ALERT['server_name']} ({ILO['host']}) "
        f"every {ALERT['interval_sec']}s, threshold={ALERT['threshold']}%, "
        f"repeat alerts every {ALERT['repeat_sec']}s")

    start_dashboard()

    while True:
        try:
            data         = fetch_fan_data()
            all_fans     = data.get("Fans", [])
            all_temps    = data.get("Temperatures", [])
            over_fans, _ = check_fans(data)
            over_names   = {f["name"] for f in over_fans}

            with _reading_lock:
                _last_reading["fans"]    = all_fans
                _last_reading["temps"]   = all_temps
                _last_reading["updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                _last_reading["error"]   = None
                _history.append({
                    "ts":   datetime.now().strftime("%H:%M:%S"),
                    "fans": {f.get("Name", "?"): f.get("Reading") for f in all_fans if f.get("Reading") is not None},
                    "temps": {t.get("Name", "?"): t.get("ReadingCelsius") for t in all_temps if t.get("ReadingCelsius") is not None},
                })

            now = time.monotonic()
            new_alerts = [f for f in over_fans if f["name"] not in alert_state]
            repeat_due = bool(alert_state) and (now - last_alert_time) >= ALERT["repeat_sec"]

            if new_alerts or repeat_due:
                reason = "new fan(s) over threshold" if new_alerts else "repeat reminder"
                log(f"ALERT — {len(over_fans)} fan(s) above {ALERT['threshold']}% ({reason})")
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                subject   = (
                    f"[ALERT] {ALERT['server_name']} – "
                    f"{len(over_fans)} fan(s) above {ALERT['threshold']}% – {timestamp}"
                )
                msg = build_email(subject, over_fans, all_fans, is_recovery=False)
                send_email(msg)
                log(f"Alert email sent to {', '.join(EMAIL['to_addrs'])}")
                alert_state    = over_names
                last_alert_time = now

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
                alert_state    = set()
                last_alert_time = 0.0

            if not new_alerts and not repeat_due and not recovered:
                status = f"{len(over_fans)} above threshold" if over_fans else "all OK"
                log(f"Check complete — {status}")

        except urllib.error.URLError as e:
            with _reading_lock:
                _last_reading["error"] = str(e.reason)
            log(f"ERROR: Cannot reach iLO at {ILO['host']} — {e.reason}")
        except Exception as e:
            with _reading_lock:
                _last_reading["error"] = str(e)
            log(f"ERROR: {e}")

        time.sleep(ALERT["interval_sec"])


if __name__ == "__main__":
    run()
