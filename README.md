# Kubernetes Scaling and Rolling Updates

## Objective
Implement scalability and deployment-update strategies with Kubernetes: scale replicas, perform rolling updates, monitor deployment status, validate application availability and analyse resource utilisation.

## What this project does
All experiments run on a 3-node Kind cluster, while a background **probe** sends 10 requests per second through the Service and records every response (status, version, pod, latency).

| # | Experiment | What is measured |
|---|---|---|
| 1 | **Manual scaling** 3 → 6 → 2 → 3 | Time until all pods are Ready |
| 2 | **Rolling update** 1.0 → 2.0 (`maxSurge 1`, `maxUnavailable 0`) | Failed requests, availability, versions served, latency, pod-state timeline |
| 3 | **Faulty release** 3.0 (readiness never passes) then `kubectl rollout undo` | Stalled rollout, old pods keep serving, rollback time, availability |
| 4 | **Resource utilisation + autoscaling** with metrics-server and a HorizontalPodAutoscaler (3–6 pods, 50 % CPU) under generated load | CPU %, replicas over time, peak pods, time back to minimum, latency under load |

## Files
| File | Purpose |
|---|---|
| `app14/app.py` | Versioned Flask service: `/`, `/version`, `/health`, `/ready`, `/work?ms=N` (burns CPU) |
| `app14/Dockerfile` | One Dockerfile, three images via build args `VERSION` and `BROKEN` (base image selectable with `BASE`) |
| `kind-config-task14.yaml` | Cluster definition; host port **8100** → NodePort **30100** |
| `k8s14/00-namespace.yaml` | Namespace `scale-demo` |
| `k8s14/01-deployment.yaml` | Deployment `web`: 3 replicas, RollingUpdate, probes, requests/limits, `progressDeadlineSeconds: 60` |
| `k8s14/02-service.yaml` | NodePort Service `web` (30100) |
| `k8s14/optional/hpa.yaml` | HorizontalPodAutoscaler (applied during the autoscaling experiment) |
| `deploy_scaling.py` | Runs all experiments and saves measurements |
| `Task14_Scaling_RollingUpdates.ipynb` | Notebook version (interactive commands) |
| `build_report.py` | Builds the PDF report, including charts, from the evidence |
| `evidence/` | `run_log.json`, `run_log.txt`, `results.json`, screenshots |
| `Task14_Scaling_Report.pdf` | Final report |

## Prerequisites
Docker Desktop (running), `kubectl`, `kind`, Python 3.9+ and `pip install pillow reportlab matplotlib`. Internet access is required (base image and the metrics-server manifest from GitHub).

## How to run (about 15–20 minutes)
```bash
python deploy_scaling.py             # prints live progress, including HPA replica counts
# optional: screenshot http://localhost:8100 → evidence/browser_app.png
python build_report.py --name "Your Name" --id "Your ID" --github <repo-url>
```
Cleanup (after submitting): `kind delete cluster --name task14`

## Architecture
```
Probe + load generator ► localhost:8100 ► NodePort 30100 ► Service web ► ready pods only
Deployment web ─ ReplicaSet per version (1.0 / 2.0 / 3.0)
HPA ◄─ metrics-server ◄─ kubelets      HPA changes Deployment replicas (min 3 · max 6 · 50 % CPU of 100m request)
```

## Key configuration
| Setting | Value | Why |
|---|---|---|
| `strategy` | RollingUpdate, maxSurge 1, maxUnavailable 0 | New pod must be ready before an old one is removed – capacity never drops |
| `readinessProbe` | `GET /ready` every 2 s | A faulty release never receives traffic |
| `livenessProbe` | `GET /health` every 10 s | Restarts a hung process independently of readiness |
| `progressDeadlineSeconds` | 60 | A stalled rollout is reported as failed after one minute |
| `resources` | requests 100m/64Mi, limits 200m/128Mi | Requests are the basis of the HPA's utilisation percentage |
| HPA behaviour | scale-up +3 pods/15 s, scale-down window 30 s | Quick reaction; shortened cool-down (default 300 s) so the demo finishes |

## Outputs
- `evidence/run_log.json` – every command and its real output
- `evidence/results.json` – measurements (scaling times, probe summaries, pod timelines, HPA timeline)
- `Task14_Scaling_Report.pdf` – scaling documentation, monitoring screenshots, performance observations; all tables and charts are computed from the recorded measurements

## Troubleshooting
| Problem | Fix |
|---|---|
| Docker Hub error `500 … auth.docker.io` | Temporary Docker Hub issue – the script automatically retries with `public.ecr.aws/docker/library/python:3.12-slim`; otherwise retry later or `docker logout` |
| `kubectl top` shows no data | metrics-server could not be installed (needs internet) or is still starting; wait a minute and re-run |
| Port 8100 in use | Change `hostPort` in `kind-config-task14.yaml` and recreate the cluster |
| Pods `Pending` / slow machine | Delete other Kind clusters, increase Docker Desktop CPU/memory |
| CPU numbers look different between runs | Everything shares one laptop's CPU – values are indicative |

## Limitations
Single machine (CPU and latency depend on other load); synthetic CPU workload; shortened HPA cool-down; probe goes through Docker Desktop's network path; pods are scaled but not nodes.

## Deliverables checklist
- [ ] Scaling documentation (report Sections 4 and 7)
- [ ] Monitoring screenshots (report Section 6 and charts)
- [ ] Performance observations (report Sections 7 and 8)
- [ ] Source as `.py` / `.ipynb`
