# Network Incident Response Simulator

A small home-lab project that detects a simulated port scan in real time and
responds automatically — logging the incident, firing a (simulated) alert,
and blocking the offending IP with `iptables` — all visible on a live Flask
dashboard.

Built entirely in an isolated VirtualBox lab (two Ubuntu VMs on a private
internal network, no internet-facing exposure) as a hands-on way to learn
the core loop of incident response: **detect → log → alert → respond.**

## Architecture

```
 attacker-vm                          target-vm
┌───────────────────┐   TCP SYNs    ┌──────────────────────────────────────┐
│ simulate_scan.py   │ ───────────▶ │ detector.py (scapy sniffer)           │
│ (scapy, sends SYNs  │              │  - tracks distinct ports/src IP       │
│  to 15 ports)       │              │  - flags a scan at 10 ports / 5s      │
└───────────────────┘               │  - logs to incidents.log (JSON lines) │
                                     │  - writes a simulated alert to        │
                                     │    alerts.log ("ALERT SENT (simulated)")│
                                     │  - auto-blocks the source IP via      │
                                     │    iptables                           │
                                     └───────────────┬────────────────────────┘
                                                      │ reads incidents.log
                                                      ▼
                                     ┌──────────────────────────────────────┐
                                     │ app.py (Flask)                        │
                                     │  - / → dashboard.html                 │
                                     │  - /api/incidents → JSON              │
                                     └───────────────┬────────────────────────┘
                                                      │ polls every 3s
                                                      ▼
                                     ┌──────────────────────────────────────┐
                                     │ dashboard.html                        │
                                     │  live table of detected incidents     │
                                     └──────────────────────────────────────┘
```

**Pipeline:** `simulate_scan.py` sends SYN packets to a range of ports on
the target. `detector.py` sniffs traffic with `scapy`, and if it sees ≥10
distinct destination ports from the same source IP within a 5-second
window, it treats that as a port scan and:

1. Logs a `port_scan` incident to `incidents.log` (JSON lines).
2. Writes a clearly-labeled **`ALERT SENT (simulated)`** line to
   `alerts.log` and stdout — a stand-in for a real Slack/email webhook call.
3. Automatically blocks the source IP with `iptables -A INPUT -s <ip> -j DROP`,
   and logs that as its own `auto_block` incident.

`app.py` (Flask) serves a dashboard that polls `/api/incidents` every 3
seconds and renders the incident log as a live-updating table.

## How the detection works

The rule is simple: if one IP hits **10 or more different ports within 5 seconds**, treat it
as a scan. Those two numbers are `SCAN_THRESHOLD` and `WINDOW` at the top of `detector.py`.

Only TCP packets with the SYN flag set get counted. Every time a packet arrives, hits older
than 5 seconds get dropped from the list, which is what makes the window slide. After an
alert fires, that IP's counter resets so one scan produces one alert instead of a stream of
them.

I picked 10 and 5 by hand for a quiet lab network. Normal clients only talk to a handful of
ports, so 10 in five seconds is well above anything legitimate, and it is still fast enough
to catch nmap at its default speed. On a real network you would want to measure a week of
normal traffic first and tune from that, rather than guessing like I did here.

### Ways around it

This rule is easy to evade, and it is worth being clear about how:

| Evasion | Why it works |
| ------- | ------------ |
| Scan slowly (`nmap -T1`) | Never reaches 10 ports inside a 5 second window |
| Scan from several machines at once | The count is per IP, so no single one crosses the line |
| FIN, NULL or Xmas scans | Those do not set the SYN flag, and I only count SYN packets |
| UDP scans | The sniffer only looks at TCP |
| Go straight for one known port | One port is not a scan, so there is nothing to spot |
| Fake the source IP | The block lands on the fake address, not the real attacker |

### Why automatic blocking is risky

That last row is the important one. When the detector fires it runs
`iptables -A INPUT -s <ip> -j DROP`, with no allowlist and no expiry. So if someone fakes
their source IP, they can pick which address gets blocked. Fake the default gateway or the
DNS server, trigger the threshold, and the detector firewalls off the network it is
supposed to be protecting. The tool becomes the attack.

This is true of automatic blocking in general, not just this project. Real systems deal with
it by:

- keeping an allowlist of things that must never be blocked (gateway, DNS, management hosts)
- making block rules expire after a while instead of being permanent
- requiring more than one signal before acting
- asking a human first when the block would affect a lot of traffic

None of that is here. This project is a demonstration of the detect, log, alert, respond
loop, which is why the instructions below are strict about only running it in an isolated
lab.

### Other rough edges

- `port_hits` keeps an entry for every IP it has ever seen, so memory grows over a long run.
  Fine for a lab, but a real sensor would need to clear out old entries.
- The list of blocked IPs lives in memory, so restarting the detector forgets what it has
  already blocked even though the iptables rules are still there.
- There is no allowlist, so something like an internal vulnerability scanner would get
  blocked along with everything else.

## What it does and does not cover

**It covers:** someone on the same network segment scanning ports to work out what is
running, usually as a first step before trying to break in.

**It does not cover:** attacks over anything other than TCP, attacks against the application
itself, an attacker who already has valid credentials, or anything that happens after
someone is already inside.

Two parts are deliberately faked rather than real:

| Part | What it would be in production | Why it is faked here |
| ---- | ------------------------------ | -------------------- |
| Alerting | PagerDuty, SNS, or a Slack webhook | No external accounts needed to show the pipeline working |
| Log storage | Splunk, Elastic, or Sentinel | A plain file keeps the project easy to run and read |

The incident log is one JSON object per line, which is the format most SIEM tools ingest
directly, so pointing a real one at it would not take much.

## Project layout

```
incident-response-project/
├── attacker/
│   └── simulate_scan.py       # sends the simulated port scan
├── detector/
│   ├── detector.py            # sniffs traffic, detects, logs, alerts, blocks
│   ├── app.py                 # Flask app serving the dashboard + API
│   └── templates/
│       └── dashboard.html     # live incident table (polls every 3s)
└── README.md
```

## How to run it

This is designed to run across two VMs on an isolated internal network —
**do not** run the detector/blocking side against a host you don't control.

**Lab setup**
- Two VMs (e.g. `attacker-vm`, `target-vm`), each with an adapter set to
  VirtualBox "Internal Network" (same network name, e.g. `labnet`) so they
  can reach each other but not your real network or the internet.
- Both VMs: `python3 -m venv venv && source venv/bin/activate`
- `attacker-vm`: `pip install scapy`
- `target-vm`: `pip install scapy flask`

**On `target-vm`** (inside `detector/`), in two terminals:
```bash
# terminal 1 — the detector (needs root for raw packet capture)
sudo venv/bin/python3 detector.py

# terminal 2 — the dashboard
venv/bin/python3 app.py
```
Visit `http://<target-vm-ip>:5000` from a browser that can reach that VM
(directly on the VM, or via port forwarding to the host).

**On `attacker-vm`** (inside `attacker/`):
```bash
sudo venv/bin/python3 simulate_scan.py <target-vm-ip>
```

Within a few seconds the dashboard should show a `port_scan` row, followed
by an `auto_block` row. Check `alerts.log` on `target-vm` for the simulated
alert line. To re-test, remove the block first:
```bash
sudo iptables -D INPUT -s <attacker-ip> -j DROP
```

## Notes / design choices

- **Simulated alerting, not a live webhook.** `send_alert()` writes a
  clearly-labeled `ALERT SENT (simulated)` line to `alerts.log` and stdout
  rather than calling a real Slack/email API — this keeps the project
  self-contained and safe to run without provisioning external credentials.
  Swapping in a real webhook is a small, isolated change to that one
  function.
- **Auto-block is real, not simulated** — it calls `iptables` directly,
  which is why the detector needs to run as root and why this only ever
  runs against lab VMs on an isolated network.
- Detection uses simple heuristics (distinct ports per source IP in a
  rolling time window) rather than a signature database — intentionally
  minimal so the detection logic is easy to read and reason about.

## Demo

The dashboard mid-detection, showing a `port_scan` incident followed by the `auto_block`
that fired in response:

<img width="2880" height="1710" alt="Live incident dashboard showing a detected port scan and the resulting automatic IP block" src="https://github.com/user-attachments/assets/5dbedd30-8966-4487-bed6-5f27b2aa992e" />
