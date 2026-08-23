"""
Integration Tests for Self-Aware Bot

Verifies end-to-end data flow via the REST API.
"""

import pytest
import multiprocessing
import time
import requests
import sys
from pathlib import Path

# Add project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.api import BotAPI

PORT = 5002
BASE_URL = f"http://localhost:{PORT}"

def start_api():
    """Start API in a separate process."""
    api = BotAPI(port=PORT)
    api.run()

@pytest.fixture(scope="module")
def api_server():
    """Fixture to start and stop API server."""
    proc = multiprocessing.Process(target=start_api, daemon=True)
    proc.start()
    time.sleep(3) # Wait for startup
    yield proc
    proc.terminate()

def test_api_status(api_server):
    """Test status endpoint."""
    resp = requests.get(f"{BASE_URL}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["status"] == "online"
    assert "health" in data

def test_analyze_flow_normal(api_server):
    """Test analyzing a normal network flow."""
    # CTU-13 features (example normal flow)
    # proto, sport, dport, sbytes, dbytes, ...
    payload = {
        "SrcAddr": "192.168.1.10",
        "DstAddr": "8.8.8.8",
        "Sport": 54321,
        "Dport": 443,
        "Proto": "tcp",
        "Dur": 0.5,
        "TotPkts": 10,
        "SrcBytes": 500,
        "DstBytes": 5000,
        # Feature columns expected by model_manager._prepare_features for ctu13
        # proto_encoded, dur, etc.
        # Note: In a real test, keys must match exactly what model_manager expects
        # For ctu13, it uses: dur, proto, dir, state, sbytes, dbytes, totpkts, totbytes, srcbytes
        "dur": 1.0,
        "proto_encoded": 1, # tcp
        "sbytes": 100,
        "dbytes": 200,
        "totpkts": 5,
        "totbytes": 300,
        "srcbytes": 100
    }
    
    resp = requests.post(f"{BASE_URL}/analyze/flow", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    
    assert "threat" in data
    assert "risk" in data
    assert "decision" in data
    assert data["risk"]["risk_score"] < 50 # Should be low risk for normal traffic

def test_analyze_keystroke_anomaly(api_server):
    """Test analyzing keystroke data (simulated anomaly)."""
    # Create a dummy feature vector of length 23 (standard for this project)
    # Random values might trigger anomaly depending on generic model (usually requires trained data)
    # We'll just verify the pipeline accepts it.
    
    features = [0.1] * 23 
    payload = {"features": features}
    
    resp = requests.post(f"{BASE_URL}/analyze/keystroke", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    
    assert "auth_result" in data
    assert "decision" in data
    
    # Check if state updated (send second request to status)
    status_resp = requests.get(f"{BASE_URL}/status")
    status_data = status_resp.json()
    # If anomaly detected, risk score would increase. 
    # Since we can't guarantee model output on dummy data, we just check field existence.
    assert "risk_score" in status_data

if __name__ == "__main__":
    # For manual running
    sys.exit(pytest.main(["-v", __file__]))
