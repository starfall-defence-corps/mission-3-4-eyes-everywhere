#!/usr/bin/env python3
"""
sdc-collector — central SIEM sink for MOS 4 "Eyes Everywhere" (range infra)
===========================================================================
Opaque range infrastructure. Cadets never read this. It PROVES telemetry is
actually delivered (behavioural), not merely configured:

  * Syslog receiver (UDP+TCP :5514) — the target of the fleet's rsyslog
    forwarding. Tagged lines (`sdc_eyes` = syslog channel, `sdc_audit` = audit
    channel) carrying a `nonce=<token>` are recorded and indexed by nonce.
  * Agent ingest (HTTP :8081, POST /tel/v1/events) — the osquery-style
    `fleetquery` agent POSTs JSON events (channel "agent") with the node's
    per-host nonce and any watched probe files.
  * Control plane (HTTP :8080, host-mapped to 9000) — the grader arms segments,
    looks up events by nonce, relocates the collector, and reads liveness. The
    control plane always listens on 0.0.0.0 so the grader can reach it via
    localhost:9000 regardless of relocation.

Relocation (the capstone): the DATA planes (syslog + agent) bind to the ACTIVE
address only (.20, then .21 after POST /relocate). Rebinding to .21 and dropping
.20 means a node still shipping to a hardcoded 172.30.0.20 goes silent, while a
node that referenced the collector by NAME re-resolves (via the harness-rewritten
/etc/hosts) and keeps delivering. Latched state lands in the gitignored .lab/.
"""
import json
import os
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PRIMARY_IP = "172.30.0.20"
RELOCATED_IP = "172.30.0.21"
SYSLOG_PORT = 5514
AGENT_PORT = 8081
CONTROL_PORT = 80          # container :80 -> host 9000
LAB_DIR = "/lab"
NODES = ["sdc-web", "sdc-db", "sdc-comms"]

NONCE_RE = re.compile(r"nonce=([0-9A-Za-z_-]{6,})")

_lock = threading.Lock()
_state = {
    "segment": 0,
    "armed_ts": None,
    "active_ip": PRIMARY_IP,
    "relocated": False,
    "event_count": 0,
    "nodes": {n: {"syslog": 0, "audit": 0, "agent": 0, "last": None} for n in NODES},
}
_events = []                # list of {ts, source, channel, nonce, message/path}
_by_nonce = {}              # nonce -> list of events


def _now():
    return time.time()


def _write_lab():
    try:
        with _lock:
            snap = dict(_state)
        tmp = os.path.join(LAB_DIR, ".status.tmp")
        with open(tmp, "w") as f:
            json.dump(snap, f)
        os.replace(tmp, os.path.join(LAB_DIR, "status.json"))
    except Exception:
        pass


def _record(source, channel, nonce, **extra):
    ev = {"ts": _now(), "source": source, "channel": channel, "nonce": nonce}
    ev.update(extra)
    with _lock:
        _events.append(ev)
        _by_nonce.setdefault(nonce, []).append(ev)
        _state["event_count"] += 1
        if source in _state["nodes"]:
            _state["nodes"][source][channel] = _state["nodes"][source].get(channel, 0) + 1
            _state["nodes"][source]["last"] = ev["ts"]
    try:
        with open(os.path.join(LAB_DIR, "events.jsonl"), "a") as f:
            f.write(json.dumps(ev) + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Syslog parsing
# --------------------------------------------------------------------------- #
def _parse_syslog(line):
    """Extract (source, channel, nonce) from a forwarded syslog line, or None.

    Only tagged, nonce-bearing lines are recorded — the fleet forwards *.* so
    the collector must ignore the ambient log traffic and latch only the
    grader's marked events.
    """
    m = NONCE_RE.search(line)
    if not m:
        return None
    nonce = m.group(1)
    if "sdc_audit" in line:
        channel = "audit"
    elif "sdc_eyes" in line:
        channel = "syslog"
    else:
        return None
    source = None
    for tok in line.split():
        if tok in NODES:
            source = tok
            break
    if source is None:
        hm = re.search(r"host=([A-Za-z0-9._-]+)", line)
        if hm and hm.group(1) in NODES:
            source = hm.group(1)
    if source is None:
        return None
    return source, channel, nonce


# --------------------------------------------------------------------------- #
# Data-plane listeners (bound to the ACTIVE ip; rebound on relocate)
# --------------------------------------------------------------------------- #
class DataPlane:
    """Owns the syslog UDP/TCP sockets and the agent HTTP server for one IP."""

    def __init__(self, ip):
        self.ip = ip
        self.stop = threading.Event()
        self.socks = []
        self.agent_srv = None

    def start(self):
        # Syslog UDP
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        u.bind((self.ip, SYSLOG_PORT))
        u.settimeout(0.5)
        self.socks.append(u)
        threading.Thread(target=self._udp_loop, args=(u,), daemon=True).start()
        # Syslog TCP
        t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        t.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        t.bind((self.ip, SYSLOG_PORT))
        t.listen(64)
        t.settimeout(0.5)
        self.socks.append(t)
        threading.Thread(target=self._tcp_loop, args=(t,), daemon=True).start()
        # Agent HTTP
        self.agent_srv = ThreadingHTTPServer((self.ip, AGENT_PORT), _AgentHandler)
        threading.Thread(target=self.agent_srv.serve_forever, daemon=True).start()

    def shutdown(self):
        self.stop.set()
        for s in self.socks:
            try:
                s.close()
            except Exception:
                pass
        if self.agent_srv:
            try:
                self.agent_srv.shutdown()
                self.agent_srv.server_close()
            except Exception:
                pass

    def _udp_loop(self, u):
        while not self.stop.is_set():
            try:
                data, _ = u.recvfrom(65535)
            except (socket.timeout, OSError):
                continue
            for line in data.decode("utf-8", "replace").splitlines():
                parsed = _parse_syslog(line)
                if parsed:
                    _record(parsed[0], parsed[1], parsed[2], message=line[:300])

    def _tcp_loop(self, t):
        while not self.stop.is_set():
            try:
                conn, _ = t.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._tcp_conn, args=(conn,), daemon=True).start()

    def _tcp_conn(self, conn):
        conn.settimeout(5)
        buf = b""
        try:
            while not self.stop.is_set():
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    parsed = _parse_syslog(line.decode("utf-8", "replace"))
                    if parsed:
                        _record(parsed[0], parsed[1], parsed[2], message=line[:300].decode("utf-8", "replace"))
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass


class _AgentHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path.rstrip("/") != "/tel/v1/events":
            self.send_response(404)
            self.end_headers()
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        nonce = str(body.get("nonce", ""))
        source = str(body.get("source", ""))
        if nonce and source:
            _record(source, "agent", nonce,
                    node_nonce=body.get("node_nonce"),
                    path=body.get("path"),
                    event_type=body.get("event_type", "heartbeat"))
        self.send_response(200)
        self.send_header("Content-Length", "3")
        self.end_headers()
        self.wfile.write(b"ok\n")


_dataplane = None
_dataplane_lock = threading.Lock()


def _relocate():
    """Add .21, move the data planes there, drop .20."""
    global _dataplane
    os.system(f"ip addr add {RELOCATED_IP}/24 dev eth0 >/dev/null 2>&1")
    time.sleep(0.3)
    with _dataplane_lock:
        old = _dataplane
        newdp = DataPlane(RELOCATED_IP)
        newdp.start()
        _dataplane = newdp
        if old:
            old.shutdown()
    with _lock:
        _state["active_ip"] = RELOCATED_IP
        _state["relocated"] = True
    _write_lab()


# --------------------------------------------------------------------------- #
# Control plane (always on 0.0.0.0:80 -> host 9000)
# --------------------------------------------------------------------------- #
class _ControlHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        u = urlparse(self.path)
        if u.path == "/healthz":
            self._json(200, {"ok": True})
        elif u.path == "/status":
            with _lock:
                self._json(200, dict(_state, now=_now()))
        elif u.path == "/tel/v1/events":
            nonce = (parse_qs(u.query).get("nonce") or [""])[0]
            with _lock:
                evs = list(_by_nonce.get(nonce, []))
            self._json(200, {"events": evs})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        from urllib.parse import urlparse
        u = urlparse(self.path)
        if u.path == "/arm":
            with _lock:
                _state["segment"] += 1
                _state["armed_ts"] = _now()
                seg, ts = _state["segment"], _state["armed_ts"]
            self._json(200, {"segment": seg, "armed_ts": ts})
        elif u.path == "/relocate":
            _relocate()
            self._json(200, {"active_ip": RELOCATED_IP})
        elif u.path == "/reset":
            with _lock:
                _events.clear()
                _by_nonce.clear()
                _state["event_count"] = 0
                for n in NODES:
                    _state["nodes"][n] = {"syslog": 0, "audit": 0, "agent": 0, "last": None}
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not found"})


def _status_writer():
    while True:
        _write_lab()
        time.sleep(2)


def main():
    global _dataplane
    os.makedirs(LAB_DIR, exist_ok=True)
    _dataplane = DataPlane(PRIMARY_IP)
    _dataplane.start()
    threading.Thread(target=_status_writer, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", CONTROL_PORT), _ControlHandler).serve_forever()


if __name__ == "__main__":
    main()
