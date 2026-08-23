# -*- coding: utf-8 -*-
"""
Burp Suite Extension for Self-Aware Hybrid Threat Analyzer.

Intercepts HTTP requests from Burp Suite, sends raw request data
to the analyzer API (/analyze_raw), and annotates risky requests.

NEW: Injects keystroke capture SDK into every HTML response,
enabling continuous behavioral biometric authentication on
any website the user visits through the proxy.

Setup:
1. Start the analyzer: python -m uvicorn app.main:app --reload
2. In Burp Suite: Extensions > Add > Python > Select this file
3. Configure browser proxy to 127.0.0.1:8080 (Burp's default)
"""

from burp import IBurpExtender
from burp import IHttpListener
from burp import IProxyListener
from java.io import PrintWriter
from java.net import URL, HttpURLConnection
from java.io import OutputStreamWriter, BufferedReader, InputStreamReader
import json
import time


API_URL = "http://127.0.0.1:8000/analyze_raw"
DEFAULT_USER = "burp_user"

# Full inline SDK - avoids mixed-content blocking on HTTPS pages
SDK_INLINE = """<script>
(function(){
if(window.__KS) return; window.__KS=1;
var API="http://127.0.0.1:8000/keystroke_freeform",B=50,U="burp_user";
var kd={},pU=0,pD=0,h=[],f=[],dd=[],kc=0;
document.addEventListener("keydown",function(e){
var k=e.key.toLowerCase();
if(k.length>1&&k!=="shift"&&k!=="backspace"&&k!=="enter"&&k!==" ")return;
if(kd[k])return; var n=performance.now(); kd[k]=n;
if(pD>0)dd.push((n-pD)/1000); pD=n;
},true);
document.addEventListener("keyup",function(e){
var n=performance.now(),k=e.key.toLowerCase(),d=kd[k];
if(!d)return; delete kd[k];
h.push((n-d)/1000);
if(pU>0)f.push((d-pU)/1000);
pU=n; kc++;
if(kc>=B)send();
},true);
function mn(a){if(!a.length)return 0;var s=0;for(var i=0;i<a.length;i++)s+=a[i];return s/a.length;}
function sd(a){if(a.length<2)return 0;var m=mn(a),s=0;for(var i=0;i<a.length;i++)s+=(a[i]-m)*(a[i]-m);return Math.sqrt(s/a.length);}
function mx(a){if(!a.length)return 0;var m=a[0];for(var i=1;i<a.length;i++)if(a[i]>m)m=a[i];return m;}
function mi(a){if(!a.length)return 0;var m=a[0];for(var i=1;i<a.length;i++)if(a[i]<m)m=a[i];return m;}
function send(){
if(h.length<5){h=[];f=[];dd=[];kc=0;return;}
var p=JSON.stringify({user_id:U,features:{hold_mean:mn(h),hold_std:sd(h),dd_mean:mn(dd),dd_std:sd(dd),
du_mean:mn(f),du_std:sd(f),ud_mean:mn(f),ud_std:sd(f),uu_mean:mn(dd),uu_std:sd(dd),
typing_speed:mn(dd)>0?1/mn(dd):0,consistency_ratio:mn(dd)>0?sd(dd)/mn(dd):0,
dd_max:mx(dd),dd_min:mi(dd),dd_range:mx(dd)-mi(dd),sample_size:kc},
page_url:location.href,timestamp:new Date().toISOString()});
try{if(navigator.sendBeacon){navigator.sendBeacon(API,new Blob([p],{type:"application/json"}));}
else{var x=new XMLHttpRequest();x.open("POST",API,true);x.setRequestHeader("Content-Type","application/json");x.send(p);}}catch(e){}
h=[];f=[];dd=[];kc=0;
}
})();
</script>"""


class BurpExtender(IBurpExtender, IHttpListener, IProxyListener):

    def registerExtenderCallbacks(self, callbacks):
        self._callbacks = callbacks
        self._helpers = callbacks.getHelpers()
        callbacks.setExtensionName("Self-Aware Threat Analyzer")

        self.stdout = PrintWriter(callbacks.getStdout(), True)
        self.stderr = PrintWriter(callbacks.getStderr(), True)
        self.stdout.println("[+] Self-Aware Threat Analyzer Extension Loaded")
        self.stdout.println("[+] API Target: " + API_URL)
        self.stdout.println("[+] Keystroke SDK injection: ENABLED")
        self.stdout.println("[+] SDK URL: " + SDK_URL)

        callbacks.registerHttpListener(self)
        callbacks.registerProxyListener(self)

    def processProxyMessage(self, messageIsRequest, message):
        """Inject keystroke SDK into proxy responses (HTML only)."""
        if messageIsRequest:
            return

        try:
            response = message.getMessageInfo().getResponse()
            if response is None:
                return

            analyzed_resp = self._helpers.analyzeResponse(response)
            headers = analyzed_resp.getHeaders()

            # Check if response is HTML
            is_html = False
            for header in headers:
                h = str(header).lower()
                if h.startswith("content-type:") and "text/html" in h:
                    is_html = True
                    break

            if not is_html:
                return

            # Extract response body
            body_offset = analyzed_resp.getBodyOffset()
            body_bytes = response[body_offset:]
            body = self._helpers.bytesToString(body_bytes)

            # Skip if SDK already injected
            if "keystroke_sdk.js" in body:
                return

            # Inject before </body> or at the end
            inject_point = body.lower().rfind("</body>")
            if inject_point >= 0:
                new_body = body[:inject_point] + "\n" + SDK_INJECT_TAG + "\n" + body[inject_point:]
            else:
                # No </body> found -- append at end
                new_body = body + "\n" + SDK_INJECT_TAG + "\n"

            # Rebuild response with new body
            new_response = self._helpers.buildHttpMessage(headers, new_body)
            message.getMessageInfo().setResponse(new_response)

            # Log injection (only first time per host to avoid spam)
            req_info = self._helpers.analyzeRequest(message.getMessageInfo())
            url = str(req_info.getUrl())
            self.stdout.println("[SDK] Injected keystroke capture into: " + url[:80])

        except Exception as e:
            self.stderr.println("[-] SDK injection error: " + str(e))

    def processHttpMessage(self, toolFlag, messageIsRequest, messageInfo):

        # Only analyze completed request-response pairs
        if messageIsRequest:
            return

        try:
            # -------------------------------------------------
            # Extract request data
            # -------------------------------------------------
            request = messageInfo.getRequest()
            response = messageInfo.getResponse()
            analyzed_req = self._helpers.analyzeRequest(messageInfo)
            headers = analyzed_req.getHeaders()

            url = str(analyzed_req.getUrl())
            method = str(headers[0]).split(" ")[0]  # GET, POST, etc.

            # Skip requests to our own API (avoid loops)
            if "127.0.0.1:8000" in url or "localhost:8000" in url:
                return

            # Extract request headers as dict
            header_dict = {}
            for i in range(1, len(headers)):
                parts = str(headers[i]).split(": ", 1)
                if len(parts) == 2:
                    header_dict[parts[0]] = parts[1]

            # Extract request body
            body_offset = analyzed_req.getBodyOffset()
            body = ""
            if body_offset < len(request):
                body_bytes = request[body_offset:]
                body = self._helpers.bytesToString(body_bytes)

            # Extract response info
            response_size = len(response) if response else 0
            response_code = 0
            if response:
                analyzed_resp = self._helpers.analyzeResponse(response)
                response_code = analyzed_resp.getStatusCode()

            # -------------------------------------------------
            # Send to analyzer API
            # -------------------------------------------------
            start_time = time.time()

            payload = {
                "user_id": DEFAULT_USER,
                "url": url,
                "method": method,
                "headers": header_dict,
                "body": body[:5000],  # Limit body size
                "response_code": response_code,
                "response_size": response_size,
                "response_time_ms": 0,
                "dst_port": analyzed_req.getUrl().getPort(),
            }

            result = self._send_to_api(payload)

            if result is None:
                return

            # -------------------------------------------------
            # Process result
            # -------------------------------------------------
            decision = result.get("fusion", {}).get("decision", "UNKNOWN")
            risk = result.get("fusion", {}).get("final_risk", 0)
            threat = result.get("threat_context")

            # Log to Burp console
            log_line = "[%s] %s %s | Risk: %.2f | Decision: %s" % (
                method, url[:80], 
                ("| THREAT: " + threat["attack_type"]) if threat else "",
                risk, decision
            )
            self.stdout.println(log_line)

            # Highlight risky requests in Burp
            if decision == "BLOCK":
                messageInfo.setHighlight("red")
                messageInfo.setComment("BLOCKED - Risk: %.2f" % risk)
            elif decision == "MFA":
                messageInfo.setHighlight("orange")
                messageInfo.setComment("MFA Required - Risk: %.2f" % risk)
            elif threat:
                messageInfo.setHighlight("yellow")
                messageInfo.setComment("Threat: " + threat["attack_type"])

        except Exception as e:
            self.stderr.println("[-] Error: " + str(e))

    def _send_to_api(self, payload):
        """Send JSON payload to the analyzer API using Java HTTP."""
        try:
            url = URL(API_URL)
            conn = url.openConnection()
            conn.setRequestMethod("POST")
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setDoOutput(True)
            conn.setConnectTimeout(3000)
            conn.setReadTimeout(5000)

            # Write request body
            body = json.dumps(payload)
            writer = OutputStreamWriter(conn.getOutputStream())
            writer.write(body)
            writer.flush()
            writer.close()

            # Read response
            if conn.getResponseCode() == 200:
                reader = BufferedReader(InputStreamReader(conn.getInputStream()))
                response = ""
                line = reader.readLine()
                while line is not None:
                    response += line
                    line = reader.readLine()
                reader.close()
                return json.loads(response)
            elif conn.getResponseCode() == 403:
                self.stdout.println("[!] ACCOUNT LOCKED by analyzer")
                return None
            else:
                self.stderr.println("[-] API returned: " + str(conn.getResponseCode()))
                return None

        except Exception as e:
            self.stderr.println("[-] API connection failed: " + str(e))
            return None

