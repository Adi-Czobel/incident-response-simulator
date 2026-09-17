from scapy.all import sniff, TCP, IP
from collections import defaultdict
import time
import json
import subprocess
from datetime import datetime

port_hits = defaultdict(list)
blocked_ips = set()
SCAN_THRESHOLD = 10   # distinct ports hit
WINDOW = 5             # within this many seconds


def log_incident(src, incident_type, detail):
    entry = {
        "type": incident_type,
        "source_ip": src,
        "detail": detail,
        "detected_at": datetime.now().isoformat()
    }
    with open("incidents.log", "a") as f:
        f.write(json.dumps(entry) + "\n")
    print("[ALERT] " + incident_type + " from " + src + ": " + detail)


def send_alert(src, detail):
    # Simulated alert hook. Swap this for a real Slack/email webhook call later.
    message = "ALERT SENT (simulated): port scan from " + src + " - " + detail
    print(message)
    with open("alerts.log", "a") as f:
        f.write(datetime.now().isoformat() + " " + message + "\n")


def block_ip(src):
    if src in blocked_ips:
        return
    try:
        subprocess.run(
            ["sudo", "iptables", "-A", "INPUT", "-s", src, "-j", "DROP"],
            check=True
        )
        blocked_ips.add(src)
        log_incident(src, "auto_block", "Blocked via iptables after port scan detection")
    except subprocess.CalledProcessError as e:
        print("Failed to block " + src + ": " + str(e))


def analyze(pkt):
    if pkt.haslayer(TCP) and pkt.haslayer(IP) and pkt[TCP].flags == 'S':
        src = pkt[IP].src
        now = time.time()
        port_hits[src].append((pkt[TCP].dport, now))
        # keep only recent hits
        port_hits[src] = [(p, t) for p, t in port_hits[src] if now - t < WINDOW]
        distinct_ports = len(set(p for p, t in port_hits[src]))
        if distinct_ports >= SCAN_THRESHOLD:
            detail = str(distinct_ports) + " ports in " + str(WINDOW) + "s"
            log_incident(src, "port_scan", detail)
            send_alert(src, detail)
            block_ip(src)
            port_hits[src] = []  # reset so it doesn't spam alerts


print("Listening for suspicious traffic... (Ctrl+C to stop)")
sniff(prn=analyze, filter="tcp", store=False)
