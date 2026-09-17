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

## Resume bullet

> Built a network incident detection and response system (Python, Flask,
> Scapy) that detects simulated port-scan attacks in real time, automatically
> blocks the offending IP via iptables, fires an alert, and surfaces all
> activity on a live web dashboard.

## Demo

*(Add a screenshot or short screen recording of the dashboard catching a
simulated scan here.)*
