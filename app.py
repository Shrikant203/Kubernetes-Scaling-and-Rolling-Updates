"""Small versioned web service used for the scaling / rolling-update experiments."""
import os
import socket
import time

from flask import Flask, jsonify, request

VERSION = os.getenv("APP_VERSION", "1.0")
BROKEN = os.getenv("APP_BROKEN", "0") == "1"          # a faulty release never becomes ready
POD = os.getenv("POD_NAME", socket.gethostname())
NODE = os.getenv("NODE_NAME", "unknown")
COLORS = {"1": "#1F5FA8", "2": "#1E8E4E", "3": "#C0392B"}
app = Flask(__name__)


@app.get("/")
def home():
    color = COLORS.get(VERSION.split(".")[0], "#444")
    return (f"<body style='font-family:sans-serif;text-align:center;margin:0;padding-top:90px;background:{color};color:white'>"
            f"<h1 style='font-size:64px;margin:0'>Version {VERSION}</h1>"
            f"<p style='font-size:22px'>Pod <b>{POD}</b></p><p style='font-size:18px'>Node {NODE}</p></body>")


@app.get("/version")
def version():
    return jsonify(version=VERSION, pod=POD, node=NODE)


@app.get("/health")                                     # liveness: process is alive
def health():
    return jsonify(status="ok")


@app.get("/ready")                                      # readiness: release is healthy
def ready():
    return (jsonify(status="not ready", version=VERSION), 503) if BROKEN else jsonify(status="ready", version=VERSION)


@app.get("/work")                                       # burns CPU for `ms` milliseconds (load generator target)
def work():
    ms = min(int(request.args.get("ms", 50)), 2000)
    end, n = time.perf_counter() + ms / 1000.0, 0
    while time.perf_counter() < end:
        n += 1
    return jsonify(version=VERSION, pod=POD, burned_ms=ms)
