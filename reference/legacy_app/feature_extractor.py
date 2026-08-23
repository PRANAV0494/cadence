"""
HTTP Feature Extractor for Self-Aware Hybrid Threat Analyzer.

Converts raw HTTP request/response metadata into:
1. Network features (79-dim vector for CICIDS2017 XGBoost model)
2. Attack signature detection (SQLi, XSS, path traversal, etc.)
"""

import re
import math
import time
from urllib.parse import urlparse, parse_qs


# ---------------------------------------------------------------
# Attack Signature Patterns
# ---------------------------------------------------------------
SQLI_PATTERNS = [
    r"(\b(union|select|insert|update|delete|drop|alter|create)\b.*\b(from|into|table|database)\b)",
    r"('|\")(\s)*(or|and)(\s)+(1|true|'|\")",
    r"(--|#|/\*)",
    r"(\bor\b\s+\d+\s*=\s*\d+)",
    r"(\bwaitfor\b\s+\bdelay\b)",
    r"(\bexec\b|\bexecute\b)(\s)*(\(|@)",
]

XSS_PATTERNS = [
    r"(<script[\s>])",
    r"(on\w+\s*=)",
    r"(javascript\s*:)",
    r"(<\s*img[^>]+onerror)",
    r"(<\s*svg[^>]+onload)",
    r"(document\.(cookie|location|write))",
    r"(alert\s*\(|confirm\s*\(|prompt\s*\()",
]

PATH_TRAVERSAL_PATTERNS = [
    r"(\.\.\/|\.\.\\)",
    r"(%2e%2e%2f|%2e%2e\/|\.\.%2f)",
    r"(etc\/passwd|etc\\passwd)",
    r"(boot\.ini|win\.ini)",
]

COMMAND_INJECTION_PATTERNS = [
    r"(;\s*(ls|cat|whoami|id|pwd|uname))",
    r"(\|\s*(ls|cat|whoami|id|pwd))",
    r"(`[^`]+`)",
    r"(\$\([^)]+\))",
]


class FeatureExtractor:
    """
    Extracts features from raw HTTP request metadata for the threat analyzer.
    """

    def extract_attack_signatures(self, url, method, headers, body):
        """
        Detect known attack patterns in the HTTP request.
        Returns attack type, severity, and confidence.
        """
        full_payload = f"{url} {body}".lower()
        header_str = " ".join(f"{k}: {v}" for k, v in headers.items()).lower() if headers else ""
        combined = f"{full_payload} {header_str}"

        detections = []

        for pattern in SQLI_PATTERNS:
            if re.search(pattern, combined, re.IGNORECASE):
                detections.append(("SQL_INJECTION", 0.9, 0.85))
                break

        for pattern in XSS_PATTERNS:
            if re.search(pattern, combined, re.IGNORECASE):
                detections.append(("XSS", 0.8, 0.80))
                break

        for pattern in PATH_TRAVERSAL_PATTERNS:
            if re.search(pattern, combined, re.IGNORECASE):
                detections.append(("PATH_TRAVERSAL", 0.85, 0.82))
                break

        for pattern in COMMAND_INJECTION_PATTERNS:
            if re.search(pattern, combined, re.IGNORECASE):
                detections.append(("COMMAND_INJECTION", 0.95, 0.88))
                break

        if not detections:
            return None

        # Return the highest severity detection
        detections.sort(key=lambda x: x[1], reverse=True)
        attack_type, severity, confidence = detections[0]

        return {
            "attack_type": attack_type,
            "severity": severity,
            "confidence": confidence,
            "all_detections": [
                {"type": d[0], "severity": d[1], "confidence": d[2]}
                for d in detections
            ]
        }

    def extract_network_features(
        self,
        url,
        method,
        headers,
        body,
        response_code=0,
        response_size=0,
        response_time_ms=0,
        src_port=0,
        dst_port=80,
        protocol=6,  # TCP
    ):
        """
        Convert raw HTTP request data into a 79-dimensional feature vector
        matching the CICIDS2017 model's expected input.

        Many CICIDS features relate to flow-level packet data that can't be
        perfectly derived from HTTP alone. We approximate using request metadata
        and use sensible defaults for unmeasurable features.
        """
        parsed = urlparse(url)
        params = parse_qs(parsed.query)

        request_size = len(body.encode("utf-8")) if body else 0
        header_count = len(headers) if headers else 0
        url_length = len(url)
        param_count = len(params)
        path_depth = len([p for p in parsed.path.split("/") if p])

        # Estimate packet sizes from HTTP data
        fwd_packet_len = request_size + sum(len(str(v)) for v in (headers or {}).values())
        bwd_packet_len = response_size

        # Time-based features (convert ms to microseconds for CICIDS format)
        flow_duration = max(response_time_ms * 1000, 1)  # microseconds
        fwd_iat = flow_duration * 0.3
        bwd_iat = flow_duration * 0.7

        # Build 79-feature vector (ordered to match CICIDS2017 training)
        features = [
            float(src_port),                          # 0: Src Port
            float(dst_port),                          # 1: Dst Port
            float(protocol),                          # 2: Protocol
            float(flow_duration),                     # 3: Flow Duration
            float(1 + param_count),                   # 4: Total Fwd Packet
            float(1),                                 # 5: Total Bwd packets
            float(fwd_packet_len),                    # 6: Total Length of Fwd Packet
            float(bwd_packet_len),                    # 7: Total Length of Bwd Packet
            float(fwd_packet_len),                    # 8: Fwd Packet Length Max
            float(min(20, fwd_packet_len)),           # 9: Fwd Packet Length Min
            float(fwd_packet_len / max(1, 1 + param_count)),  # 10: Fwd Packet Length Mean
            float(fwd_packet_len * 0.1),              # 11: Fwd Packet Length Std
            float(bwd_packet_len),                    # 12: Bwd Packet Length Max
            float(min(20, bwd_packet_len)),           # 13: Bwd Packet Length Min
            float(bwd_packet_len),                    # 14: Bwd Packet Length Mean
            float(bwd_packet_len * 0.1),              # 15: Bwd Packet Length Std
            float((fwd_packet_len + bwd_packet_len) / max(flow_duration, 1) * 1e6),  # 16: Flow Bytes/s
            float(2 / max(flow_duration, 1) * 1e6),   # 17: Flow Packets/s
            float(flow_duration / 2),                  # 18: Flow IAT Mean
            float(flow_duration * 0.2),                # 19: Flow IAT Std
            float(flow_duration),                      # 20: Flow IAT Max
            float(0),                                  # 21: Flow IAT Min
            float(fwd_iat),                            # 22: Fwd IAT Total
            float(fwd_iat),                            # 23: Fwd IAT Mean
            float(fwd_iat * 0.1),                      # 24: Fwd IAT Std
            float(fwd_iat),                            # 25: Fwd IAT Max
            float(0),                                  # 26: Fwd IAT Min
            float(bwd_iat),                            # 27: Bwd IAT Total
            float(bwd_iat),                            # 28: Bwd IAT Mean
            float(bwd_iat * 0.1),                      # 29: Bwd IAT Std
            float(bwd_iat),                            # 30: Bwd IAT Max
            float(0),                                  # 31: Bwd IAT Min
            float(1 if method == "POST" else 0),       # 32: Fwd PSH Flags
            float(0),                                  # 33: Bwd PSH Flags
            float(0),                                  # 34: Fwd URG Flags
            float(0),                                  # 35: Bwd URG Flags
            float(header_count * 32),                  # 36: Fwd Header Length
            float(6 * 32),                             # 37: Bwd Header Length
            float(1 / max(flow_duration, 1) * 1e6),    # 38: Fwd Packets/s
            float(1 / max(flow_duration, 1) * 1e6),    # 39: Bwd Packets/s
            float(min(fwd_packet_len, bwd_packet_len)),# 40: Packet Length Min
            float(max(fwd_packet_len, bwd_packet_len)),# 41: Packet Length Max
            float((fwd_packet_len + bwd_packet_len) / 2),# 42: Packet Length Mean
            float(abs(fwd_packet_len - bwd_packet_len) / 2),# 43: Packet Length Std
            float(((fwd_packet_len - bwd_packet_len) / 2) ** 2),# 44: Packet Length Variance
            float(0),                                  # 45: FIN Flag Count
            float(1),                                  # 46: SYN Flag Count
            float(0),                                  # 47: RST Flag Count
            float(1 if method == "POST" else 0),       # 48: PSH Flag Count
            float(1),                                  # 49: ACK Flag Count
            float(0),                                  # 50: URG Flag Count
            float(0),                                  # 51: CWR Flag Count
            float(0),                                  # 52: ECE Flag Count
            float(bwd_packet_len / max(fwd_packet_len, 1)),  # 53: Down/Up Ratio
            float((fwd_packet_len + bwd_packet_len) / 2),    # 54: Average Packet Size
            float(fwd_packet_len),                     # 55: Fwd Segment Size Avg
            float(bwd_packet_len),                     # 56: Bwd Segment Size Avg
            float(0),                                  # 57: Fwd Bytes/Bulk Avg
            float(0),                                  # 58: Fwd Packet/Bulk Avg
            float(0),                                  # 59: Fwd Bulk Rate Avg
            float(0),                                  # 60: Bwd Bytes/Bulk Avg
            float(0),                                  # 61: Bwd Packet/Bulk Avg
            float(0),                                  # 62: Bwd Bulk Rate Avg
            float(1 + param_count),                    # 63: Subflow Fwd Packets
            float(fwd_packet_len),                     # 64: Subflow Fwd Bytes
            float(1),                                  # 65: Subflow Bwd Packets
            float(bwd_packet_len),                     # 66: Subflow Bwd Bytes
            float(65535),                              # 67: FWD Init Win Bytes
            float(65535),                              # 68: Bwd Init Win Bytes
            float(1 + param_count),                    # 69: Fwd Act Data Pkts
            float(20),                                 # 70: Fwd Seg Size Min
            float(flow_duration * 0.8),                # 71: Active Mean
            float(flow_duration * 0.1),                # 72: Active Std
            float(flow_duration),                      # 73: Active Max
            float(flow_duration * 0.5),                # 74: Active Min
            float(0),                                  # 75: Idle Mean
            float(0),                                  # 76: Idle Std
            float(0),                                  # 77: Idle Max
            float(0),                                  # 78: Idle Min
        ]

        return features
