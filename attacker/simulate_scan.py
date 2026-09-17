from scapy.all import IP, TCP, sr1
import sys
import time

target_ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.56.101"  # replace with target-vm IP

print(f"Simulating port scan against {target_ip}...")
for port in range(20, 35):  # scan 15 ports — enough to trip the threshold
    pkt = IP(dst=target_ip) / TCP(dport=port, flags="S")
    sr1(pkt, timeout=0.5, verbose=0)
    time.sleep(0.1)  # small delay so it's a "scan," not a flood
print("Done.")
