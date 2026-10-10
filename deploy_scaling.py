#!/usr/bin/env python3
"""Task 14 - Kubernetes scaling and rolling updates (Kind).

    python deploy_scaling.py            # run every experiment (about 15-20 minutes)
    python deploy_scaling.py --cleanup  # ... and delete the cluster afterwards

Experiments (all measured while a background probe checks availability through the Service):
  1. Manual scaling 3 -> 6 -> 2 -> 3 with timing
  2. Rolling update 1.0 -> 2.0 (maxSurge 1, maxUnavailable 0)
  3. Faulty release 3.0 (never ready): rollout stalls, old pods keep serving, rollback with 'rollout undo'
  4. Resource utilisation (metrics-server) and CPU-based autoscaling with a HorizontalPodAutoscaler under load
Every command + real output goes to evidence/run_log.json, all measurements to evidence/results.json.
"""
import argparse, json, os, shutil, statistics, subprocess, sys, threading, time, urllib.error, urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent
EVID = ROOT / "evidence"; EVID.mkdir(exist_ok=True)
NS, CLUSTER = "scale-demo", "task14"
BASE = "http://localhost:8100"
BASES = ["python:3.12-slim", "public.ecr.aws/docker/library/python:3.12-slim"]
MS_URL = "https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml"
LOG, RES = [], {}
BASH = "/bin/bash" if os.path.exists("/bin/bash") else None
T0 = time.time()


# ------------------------------------------------------------------ helpers
def sh(cmd, timeout=900):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, executable=BASH)
    return p.returncode, (p.stdout + p.stderr).strip()


def record(title, cmd, output, rc=0):
    print(f"\n=== {title} ===\n$ {cmd}\n{output}", flush=True)
    LOG.append({"title": title, "cmd": cmd, "output": output, "rc": rc})


def run(title, cmd, check=True, timeout=900):
    rc, out = sh(cmd, timeout)
    record(title, cmd, out, rc)
    if check and rc != 0:
        save(); sys.exit(f"Command failed ({rc}): {cmd}")
    return out


def run_live(title, cmd, timeout=3600, keep=14, check=True):
    print(f"\n=== {title} ===\n$ {cmd}", flush=True)
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, executable=BASH)
    lines, t0 = [], time.time()
    for line in p.stdout:
        print(line, end="", flush=True); lines.append(line.rstrip())
        if time.time() - t0 > timeout:
            p.kill(); break
    p.wait()
    LOG.append({"title": title, "cmd": cmd, "output": "\n".join(lines[-keep:]), "rc": p.returncode})
    if p.returncode != 0:
        if not check:
            LOG.pop(); return p.returncode
        save(); sys.exit(f"Command failed ({p.returncode}): {cmd}")
    return 0


def save():
    (EVID / "run_log.json").write_text(json.dumps(LOG, indent=2))
    (EVID / "results.json").write_text(json.dumps(RES, indent=2))
    with open(EVID / "run_log.txt", "w") as f:
        for e in LOG:
            f.write(f"=== {e['title']} ===\n$ {e['cmd']}\n{e['output']}\n\n")


def jget(args):
    rc, out = sh(f"kubectl {args} -o json")
    try:
        return json.loads(out)
    except Exception:
        return {}


def pods():
    """Per-pod state of the web Deployment: version (image tag), readiness, terminating."""
    res = []
    for p in jget(f"get pods -n {NS} -l app=web").get("items", []):
        st = p.get("status", {})
        ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in st.get("conditions", []))
        res.append({"name": p["metadata"]["name"], "version": p["spec"]["containers"][0]["image"].split(":")[-1],
                    "ready": ready, "terminating": "deletionTimestamp" in p["metadata"], "phase": st.get("phase")})
    return res


def wait_ready(n, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        ps = [p for p in pods() if not p["terminating"]]
        if len(ps) == n and all(p["ready"] for p in ps):
            return round(time.time() - t0, 1)
        time.sleep(1)
    return None


class Probe(threading.Thread):
    """Calls GET /version through the NodePort Service in a loop and records every result."""
    def __init__(self, interval=0.1, path="/version"):
        super().__init__(daemon=True); self.interval, self.path, self.stop_flag, self.rows = interval, path, False, []

    def run(self):
        while not self.stop_flag:
            t = time.time(); status, ver = 0, None
            try:
                r = urllib.request.urlopen(BASE + self.path, timeout=3)
                status = r.status; ver = json.loads(r.read().decode()).get("version")
            except urllib.error.HTTPError as e:
                status = e.code
            except Exception:
                status = 0
            self.rows.append((t, status, ver, time.time() - t))
            time.sleep(self.interval)

    def stop(self):
        self.stop_flag = True; self.join(timeout=10)

    def summary(self):
        n = len(self.rows); ok = sum(1 for r in self.rows if r[1] == 200)
        lat = sorted(r[3] * 1000 for r in self.rows if r[1] == 200) or [0]
        return {"requests": n, "ok": ok, "failed": n - ok, "availability_pct": round(100 * ok / n, 3) if n else 0,
                "versions": dict(Counter(r[2] for r in self.rows if r[1] == 200)),
                "latency_ms": {"p50": round(statistics.median(lat), 1), "p95": round(lat[int(0.95 * (len(lat) - 1))], 1), "max": round(lat[-1], 1)}}


def probe_text(s):
    return (f"requests sent      : {s['requests']}\nsuccessful (HTTP 200): {s['ok']}\nfailed             : {s['failed']}\n"
            f"availability       : {s['availability_pct']} %\nresponses by version: {s['versions']}\n"
            f"latency (ms)       : p50 {s['latency_ms']['p50']}  p95 {s['latency_ms']['p95']}  max {s['latency_ms']['max']}")


class Timeline(threading.Thread):
    """Samples the pod set every `interval` seconds."""
    def __init__(self, interval=1.5):
        super().__init__(daemon=True); self.interval, self.stop_flag, self.rows, self.t0 = interval, False, [], time.time()

    def run(self):
        while not self.stop_flag:
            ps = pods(); row = {"t": round(time.time() - self.t0, 1)}
            for v in sorted({p["version"] for p in ps}):
                row[f"v{v}_ready"] = sum(1 for p in ps if p["version"] == v and p["ready"] and not p["terminating"])
                row[f"v{v}_notready"] = sum(1 for p in ps if p["version"] == v and not p["ready"] and not p["terminating"])
            row["terminating"] = sum(1 for p in ps if p["terminating"])
            row["total"] = len(ps); self.rows.append(row); time.sleep(self.interval)

    def stop(self):
        self.stop_flag = True; self.join(timeout=15)


def load_image(tag):
    rc, out = sh(f"kind load docker-image {tag} --name {CLUSTER}")
    if rc != 0:     # Docker Desktop's containerd image store can break 'docker-image' loading
        rc, out = sh(f"docker save {tag} -o /tmp/scale-app.tar && kind load image-archive /tmp/scale-app.tar --name {CLUSTER}")
    return rc, out


def top_pods():
    rc, out = sh(f"kubectl top pods -n {NS} --no-headers")
    vals = []
    for l in out.splitlines():
        f = l.split()
        if len(f) >= 3 and f[1].endswith("m"):
            vals.append(int(f[1][:-1]))
    return out, vals


# ------------------------------------------------------------------ experiments
def exp_scaling():
    rows = []
    for target in (6, 2, 3):
        cur = len([p for p in pods() if not p["terminating"]])
        t0 = time.time(); rc, out = sh(f"kubectl scale deployment/web --replicas={target} -n {NS}")
        secs = wait_ready(target)
        rows.append({"from": cur, "to": target, "seconds_to_ready": secs})
        _, lst = sh(f"kubectl get pods -n {NS} -o wide")
        record(f"Scale {cur} to {target} replicas", f"kubectl scale deployment/web --replicas={target} -n {NS}",
               f"{out}\nall {target} pods Ready after {secs} s\n\n{lst}")
    RES["scaling"] = rows


def exp_rolling_update():
    probe, tl = Probe(), Timeline(); probe.start(); tl.start(); time.sleep(3)
    t0 = time.time()
    sh(f"kubectl annotate deployment/web kubernetes.io/change-cause='update image to scale-app:2.0' -n {NS} --overwrite")
    rc, out1 = sh(f"kubectl set image deployment/web web=scale-app:2.0 -n {NS}")
    rc, out2 = sh(f"kubectl rollout status deployment/web -n {NS} --timeout=240s")
    dur = round(time.time() - t0, 1); time.sleep(3); probe.stop(); tl.stop()
    record("Rolling update to 2.0", f"kubectl set image deployment/web web=scale-app:2.0 -n {NS}", f"{out1}\n{out2}\n(update took {dur} s)", rc)
    run("Rollout history", f"kubectl rollout history deployment/web -n {NS}")
    run("ReplicaSets after update", f"kubectl get rs -n {NS}")
    s = probe.summary(); record("Availability during rolling update", f"probe: GET {BASE}/version every 0.1 s", probe_text(s))
    rows, last = [], None
    for r in tl.rows:
        key = tuple((k, v) for k, v in r.items() if k not in ("t",))
        if key != last: rows.append(r); last = key
    all_keys = sorted({k for r in rows for k in r if k != "t"})
    txt = "t(s)   " + " ".join(f"{k:>12}" for k in all_keys) + "\n" + "\n".join(f"{r['t']:>5}  " + " ".join(f"{r.get(k, 0):>12}" for k in all_keys) for r in rows)
    record("Version transition timeline", "kubectl get pods (sampled every 1.5 s)", txt)
    RES["rolling_update"] = {"duration_s": dur, "summary": s, "timeline": tl.rows}


def exp_bad_release():
    probe, tl = Probe(), Timeline(); probe.start(); tl.start(); time.sleep(3)
    sh(f"kubectl annotate deployment/web kubernetes.io/change-cause='update image to scale-app:3.0 (faulty)' -n {NS} --overwrite")
    rc0, out1 = sh(f"kubectl set image deployment/web web=scale-app:3.0 -n {NS}")
    rc, out2 = sh(f"kubectl rollout status deployment/web -n {NS} --timeout=120s")
    record("Faulty release 3.0 (rollout stalls)", f"kubectl set image deployment/web web=scale-app:3.0 -n {NS}", f"{out1}\n{out2}", rc)
    run("Pods during failed rollout", f"kubectl get pods -n {NS} -o wide")
    run("Deployment conditions", f"kubectl get deployment web -n {NS} -o jsonpath='{{range .status.conditions[*]}}{{.type}}={{.status}} ({{.reason}}){{\"\\n\"}}{{end}}'")
    t0 = time.time()
    rc, out3 = sh(f"kubectl rollout undo deployment/web -n {NS}")
    rc, out4 = sh(f"kubectl rollout status deployment/web -n {NS} --timeout=180s")
    dur = round(time.time() - t0, 1); time.sleep(3); probe.stop(); tl.stop()
    record("Rollback with rollout undo", f"kubectl rollout undo deployment/web -n {NS}", f"{out3}\n{out4}\n(rollback took {dur} s)", rc)
    run("Pods after rollback", f"kubectl get pods -n {NS} -o wide")
    run("Rollout history after rollback", f"kubectl rollout history deployment/web -n {NS}")
    s = probe.summary(); record("Availability during faulty release and rollback", f"probe: GET {BASE}/version every 0.1 s", probe_text(s))
    RES["bad_release"] = {"rollback_s": dur, "stalled": rc0 == 0 and "successfully" not in out2, "summary": s, "timeline": tl.rows}


def exp_resources_and_hpa(load_s=150, cooldown_max=240):
    out, vals = top_pods()
    record("Pod resource usage (baseline)", f"kubectl top pods -n {NS}", out)
    run("Node resource usage (baseline)", "kubectl top nodes", check=False)
    RES["baseline_pod_cpu_m"] = vals
    run("Apply HPA", "kubectl apply -f k8s14/optional/hpa.yaml")
    probe = Probe(interval=0.5); probe.start()
    stop = threading.Event()
    def hammer():
        while not stop.is_set():
            try: urllib.request.urlopen(BASE + "/work?ms=100", timeout=15).read()
            except Exception: time.sleep(0.2)
    workers = [threading.Thread(target=hammer, daemon=True) for _ in range(14)]
    tl, t0, load_end, captured = [], time.time(), None, False
    for w in workers: w.start()
    print(f"\n--- generating CPU load for {load_s} s ---", flush=True)
    phase = "load"
    while True:
        t = time.time() - t0
        if phase == "load" and t >= load_s:
            stop.set(); phase = "cooldown"; load_end = round(t, 1)
            print("--- load stopped, waiting for scale-down ---", flush=True)
        h = jget(f"get hpa web -n {NS}").get("status", {})
        cur = h.get("currentReplicas"); des = h.get("desiredReplicas")
        cpu = None
        for m in h.get("currentMetrics", []) or []:
            if m.get("type") == "Resource": cpu = m["resource"]["current"].get("averageUtilization")
        ps = [p for p in pods() if not p["terminating"]]
        _, v = top_pods()
        tl.append({"t": round(t, 1), "phase": phase, "hpa_current": cur, "hpa_desired": des, "cpu_util_pct": cpu,
                   "pods": len(ps), "ready": sum(1 for p in ps if p["ready"]), "avg_cpu_m": round(sum(v) / len(v)) if v else None})
        print(f"t={t:5.0f}s {phase:8s} replicas={cur}->{des} cpu={cpu}% pods={len(ps)} avg_cpu={tl[-1]['avg_cpu_m']}m", flush=True)
        if phase == "load" and not captured and t >= load_s * 0.6:
            captured = True
            run("Pod resource usage (under load)", f"kubectl top pods -n {NS}", check=False)
            run("HPA status (under load)", f"kubectl get hpa web -n {NS}")
            run("Node resource usage (under load)", "kubectl top nodes", check=False)
        if phase == "cooldown" and (tl[-1]["pods"] <= 3 or t - load_end > cooldown_max):
            break
        time.sleep(6)
    probe.stop(); s = probe.summary()
    run("HPA status (after load)", f"kubectl get hpa web -n {NS}")
    run("Describe HPA", f"kubectl describe hpa web -n {NS} | tail -n 28")
    record("Availability during autoscaling under load", f"probe: GET {BASE}/version every 0.5 s", probe_text(s))
    run("Pods after autoscaling", f"kubectl get pods -n {NS}")
    RES["hpa"] = {"timeline": tl, "load_seconds": load_end, "peak_pods": max(r["pods"] for r in tl), "summary": s,
                  "min_replicas": 3, "max_replicas": 6, "target_cpu_pct": 50}


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--cleanup", action="store_true"); a = ap.parse_args()
    for t in ("docker", "kubectl", "kind"):
        if not shutil.which(t):
            sys.exit(f"'{t}' not found in PATH - install it first (see README.md)")
    run("Tool versions", "docker --version && kubectl version --client && kind version")

    # 1. images: 1.0 (initial), 2.0 (update) and 3.0 (faulty release)
    for ver, bad, label in (("1.0", 0, "Build image 1.0"), ("2.0", 0, "Build image 2.0"), ("3.0", 1, "Build image 3.0 (faulty)")):
        for n, base in enumerate(BASES):               # Docker Hub sometimes fails (auth 500): fall back to an AWS mirror of the same image
            rc = run_live(label, f"docker build --progress=plain --provenance=false --sbom=false --build-arg BASE={base} "
                                 f"--build-arg VERSION={ver} --build-arg BROKEN={bad} -t scale-app:{ver} app14 2>&1", check=(n == len(BASES) - 1))
            if rc == 0:
                break
            print(f"\n!! build with base image {base} failed - trying the next mirror ...", flush=True)
    run("Docker images", "docker image ls scale-app")

    # 2. cluster
    existing = run("List kind clusters", "kind get clusters", check=False)
    if CLUSTER not in existing.split():
        run("Create Kind cluster (1 control-plane + 2 workers)", f"kind create cluster --name {CLUSTER} --config kind-config-task14.yaml --wait 120s")
    run("Set kubectl context", f"kubectl config use-context kind-{CLUSTER}")
    run("Wait for all nodes Ready", "kubectl wait --for=condition=Ready nodes --all --timeout=180s")
    run("Cluster nodes", "kubectl get nodes -o wide")
    for ver in ("1.0", "2.0", "3.0"):
        rc, out = load_image(f"scale-app:{ver}")
        record(f"Load image {ver} into Kind", f"kind load docker-image scale-app:{ver} --name {CLUSTER}", out[-300:], rc)
        if rc != 0: save(); sys.exit("Could not load image into Kind")

    # 3. metrics-server (needed for kubectl top and the HPA)
    run("Install metrics-server", f"kubectl apply -f {MS_URL}", check=False)
    run("Patch metrics-server for Kind", "kubectl patch deployment metrics-server -n kube-system --type=json "
        "-p='[{\"op\":\"add\",\"path\":\"/spec/template/spec/containers/0/args/-\",\"value\":\"--kubelet-insecure-tls\"}]'", check=False)
    run("Wait for metrics-server", "kubectl rollout status deployment/metrics-server -n kube-system --timeout=180s", check=False)

    # 4. application
    run("Apply manifests", "kubectl apply -f k8s14/")
    run("Wait for initial rollout", f"kubectl rollout status deployment/web -n {NS} --timeout=240s")
    run("Get pods (initial)", f"kubectl get pods -n {NS} -o wide")
    run("Get deployment and service", f"kubectl get deploy,svc,endpointslices -n {NS}")
    ok = None
    for _ in range(20):
        try: ok = urllib.request.urlopen(BASE + "/version", timeout=5).read().decode(); break
        except Exception: time.sleep(2)
    record("Application reachable (version 1.0)", f"curl -s {BASE}/version", ok or "FAILED to reach the application", 0 if ok else 1)

    # 5. experiments
    exp_scaling()
    exp_rolling_update()
    exp_bad_release()
    for _ in range(12):                                   # metrics-server needs a moment before 'kubectl top' works
        if sh(f"kubectl top pods -n {NS}")[0] == 0: break
        time.sleep(10)
    exp_resources_and_hpa()

    run("Deployment details", f"kubectl describe deployment web -n {NS}")
    run("Recent events", f"kubectl get events -n {NS} --sort-by=.lastTimestamp | tail -n 40")
    save()
    print(f"\nDone. Logs + measurements saved in {EVID}  (total {round((time.time()-T0)/60,1)} min)")
    if a.cleanup:
        subprocess.run(f"kind delete cluster --name {CLUSTER}", shell=True)


if __name__ == "__main__":
    main()
