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

## Detection logic

A source IP is flagged when it touches **10 or more distinct destination ports within a
5-second sliding window** (`SCAN_THRESHOLD = 10`, `WINDOW = 5` in `detector.py`). Only TCP
packets with the SYN flag set are counted; the window is maintained by discarding hits older
than `WINDOW` on every packet, and a source's counter is reset after it fires so one scan
produces one alert rather than a flood.

**Why these thresholds.** Legitimate clients talk to a small, stable set of ports. Ten
distinct ports inside five seconds sits well clear of normal application behaviour while
staying tight enough to catch `nmap`'s default timing. The numbers were chosen by judgement
for a quiet lab network, not derived from measured traffic — on a real network they would need
to be tuned against an actual baseline, and the right way to pick them would be to measure the
false-positive rate across a week of normal traffic first.

### What this misses, by design

| Evasion | Why it defeats this rule |
|---|---|
| Slow scan (`nmap -T1`, one port every 30s) | Never accumulates 10 ports inside a 5s window |
| Distributed scan from multiple sources | The counter is per source IP; no single source crosses the threshold |
| FIN / NULL / Xmas scans (`nmap -sF -sN -sX`) | `detector.py` only counts packets with the SYN flag set |
| UDP scans (`nmap -sU`) | The sniffer filters on `tcp` |
| Targeting one known service | A single port is touched; there is no scan signature to see |
| Source IP spoofing | Blocks the spoofed address, not the attacker |

### The spoofing problem

The last row is the one that matters. Because the response is an automatic, permanent
`iptables -A INPUT -s <ip> -j DROP` with no allowlist and no expiry, anyone who can spoof a
source address can make this tool deny service on their behalf: spoof the default gateway, a
DNS resolver, or a monitoring host, trigger the threshold, and the detector firewalls off its
own infrastructure.

This is a general property of automated blocking, not a bug unique to this project, and it is
why production systems gate auto-blocking behind:

- an **allowlist** of infrastructure that must never be blocked (gateway, DNS, management, LB)
- **time-boxed** rules that expire, rather than permanent DROPs
- **reputation or confidence scoring** so a single heuristic cannot trigger a block alone
- **human confirmation** above a blast-radius threshold

None of those are implemented here. The project demonstrates the detect → log → alert →
respond loop; it is not safe to point at anything but an isolated lab, which is why the
instructions below are explicit about that.

### Other known limitations

- `port_hits` retains an entry for every source IP observed, so memory grows unbounded over a
  long run. Fine for a lab, not for a long-lived sensor; it needs periodic eviction.
- Blocks are tracked in an in-process `set`, so restarting the detector loses the record of
  what it has already blocked while the `iptables` rules themselves persist.
- Detection is heuristic, not signature- or behaviour-based, and there is no allowlisting of
  known scanners such as internal vulnerability management.

## Scope and threat model

**Models:** an unauthenticated attacker on the same L2 segment performing TCP port
reconnaissance as a precursor to exploitation.

**Does not model:** authenticated insiders, application-layer attacks, encrypted command and
control, lateral movement after a foothold, or any non-TCP protocol.

**Deliberately simulated rather than real:**

| Component | Production equivalent | Why simulated here |
|---|---|---|
| Alerting | PagerDuty, SNS, Slack webhook | No external credentials needed to demonstrate the pipeline |
| Log sink | Splunk, Elastic, Sentinel | JSON lines on disk keeps it dependency-free and inspectable |

The incident log is newline-delimited JSON, one object per line, so it pipes directly into any
SIEM that ingests NDJSON.

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
