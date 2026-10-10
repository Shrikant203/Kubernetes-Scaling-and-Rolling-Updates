#!/usr/bin/env python3
"""Builds Task14_Scaling_Report.pdf (Task 7 report style) from the project files and the
real output recorded by deploy_dl.py in evidence/run_log.json.

    python deploy_scaling.py
    # optional: screenshot of http://localhost:8100 -> evidence/browser_app.png
    python build_report.py --name "Your Name" --id "Your ID" [--github URL]

Needs: pip install reportlab pillow
"""
import argparse, datetime, json, math, os, re, tempfile, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table,
                                TableStyle, PageBreak, KeepTogether, Image as RLImage, Flowable)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.pdfgen import canvas as pdfcanvas

ap = argparse.ArgumentParser()
ap.add_argument("--name", default="Shrikant Daulat Nagare"); ap.add_argument("--cls", default="M.Sc. DSBDA - Part 2")
ap.add_argument("--id", default="22"); ap.add_argument("--github", default="")
ARGS = ap.parse_args()

SRC = Path(os.environ.get("T14_ROOT", Path(__file__).parent)); EV = SRC / "evidence"
FIG = Path(tempfile.mkdtemp()); OUT = SRC / "Task14_Scaling_Report.pdf"
if not (EV / "run_log.json").exists():
    raise SystemExit("evidence/run_log.json not found - run deploy_scaling.py first")
LOG = json.load(open(EV / "run_log.json"))
RES = json.load(open(EV / "results.json")) if (EV / "results.json").exists() else {}
FD = '/usr/share/fonts/truetype/dejavu/'
if not os.path.exists(FD):   # macOS / Windows: use matplotlib's bundled DejaVu fonts
    import matplotlib; FD = os.path.join(os.path.dirname(matplotlib.__file__), 'mpl-data/fonts/ttf/')

def E(prefix):
    return next((e for e in LOG if e['title'].startswith(prefix)), None)
def OUTP(prefix):
    e = E(prefix); return e['output'] if e else ''
def JS(prefix):
    try: return json.loads(OUTP(prefix))
    except Exception: return None

# ---------- fonts / colours ----------
for n, f in [('DV', 'DejaVuSans.ttf'), ('DV-B', 'DejaVuSans-Bold.ttf'), ('DV-I', 'DejaVuSans-Oblique.ttf'),
             ('DV-BI', 'DejaVuSans-BoldOblique.ttf'), ('DVM', 'DejaVuSansMono.ttf'), ('DVM-B', 'DejaVuSansMono-Bold.ttf')]:
    pdfmetrics.registerFont(TTFont(n, FD + f))
pdfmetrics.registerFontFamily('DV', normal='DV', bold='DV-B', italic='DV-I', boldItalic='DV-BI')
NAVY = colors.HexColor('#1B3A6B'); BLUE = colors.HexColor('#1F5FA8'); GREY = colors.HexColor('#5A6270')
LGREY = colors.HexColor('#EFEFEF'); LINE = colors.HexColor('#D5D5D5'); CODEBG = colors.HexColor('#0F1419')
W = A4[0] - 4 * cm  # content width

body = ParagraphStyle('body', fontName='DV', fontSize=8.6, leading=13, textColor=colors.HexColor('#222222'), spaceAfter=6)
small = ParagraphStyle('small', parent=body, fontSize=7.8, leading=11, spaceAfter=0)
cell = ParagraphStyle('cell', parent=body, fontSize=7.8, leading=10.5, spaceAfter=0)
cellb = ParagraphStyle('cellb', parent=cell, fontName='DV-B')
cellh = ParagraphStyle('cellh', parent=cell, fontName='DV-B', textColor=colors.white)
title = ParagraphStyle('title', fontName='DV-B', fontSize=21, leading=27, textColor=NAVY, spaceAfter=8)
subtitle = ParagraphStyle('sub', fontName='DV', fontSize=10, leading=14, textColor=GREY, spaceAfter=18)
h2 = ParagraphStyle('h2', fontName='DV-B', fontSize=11, leading=15, textColor=BLUE, spaceBefore=10, spaceAfter=6)
cap = ParagraphStyle('cap', fontName='DV-I', fontSize=7.6, leading=10.5, textColor=GREY, alignment=TA_CENTER, spaceBefore=3, spaceAfter=10)
bullet = ParagraphStyle('bullet', parent=body, leftIndent=14, bulletIndent=2, spaceAfter=4)
num = ParagraphStyle('num', parent=body, leftIndent=16, bulletIndent=0, spaceAfter=5)

def code(t): return f'<font face="DVM" size="7.4" backColor="#E8EEF7">&nbsp;{esc(t)}&nbsp;</font>'
def esc(t): return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
def P(t, st=body): return Paragraph(t, st)

class H1(Table):
    def __init__(self, text):
        p = Paragraph(text, ParagraphStyle('h1', fontName='DV-B', fontSize=14, leading=18, textColor=NAVY))
        Table.__init__(self, [['', p]], colWidths=[4, W - 4])
        self.setStyle(TableStyle([('BACKGROUND', (0, 0), (0, 0), BLUE), ('LEFTPADDING', (1, 0), (1, 0), 8),
                                  ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                                  ('LEFTPADDING', (0, 0), (0, 0), 0), ('RIGHTPADDING', (0, 0), (0, 0), 0)]))
        self.toc_level, self.toc_text, self.keepWithNext = 0, text, 1
        self.spaceAfter = 8; self.spaceBefore = 6
class H2(Paragraph):
    def __init__(self, text):
        Paragraph.__init__(self, text, h2); self.toc_level, self.toc_text, self.keepWithNext = 1, re.sub('<[^>]+>', '', text), 1

class CodeBlock(Flowable):
    LH, FS, PAD = 7.5, 6.1, 8
    def __init__(self, lines, start=1, wrap=118):
        Flowable.__init__(self)
        self.rows = []
        for n, l in enumerate(lines, start):
            l = l.replace('\t', '    ')
            parts = textwrap.wrap(l, wrap, drop_whitespace=False, replace_whitespace=False) or ['']
            for k, pt in enumerate(parts):
                self.rows.append((str(n) if k == 0 else '', ('↳ ' if k else '') + pt))
    def wrap(self, aw, ah):
        self.w = aw; self.h = len(self.rows) * self.LH + 2 * self.PAD; return aw, self.h
    def draw(self):
        c = self.canv; c.setFillColor(CODEBG); c.roundRect(0, 0, self.w, self.h, 3, fill=1, stroke=0)
        y = self.h - self.PAD - self.FS
        for n, t in self.rows:
            c.setFont('DVM', self.FS); c.setFillColor(colors.HexColor('#6E7681')); c.drawRightString(26, y, n)
            c.setFillColor(colors.HexColor('#D6DDE6')); c.drawString(34, y, t); y -= self.LH

# ---------- terminal-style figure renderer (real command output from run_log.json) ----------
MONO = ImageFont.truetype(FD + 'DejaVuSansMono.ttf', 28); CW = MONO.getlength('M'); LH = 42
def pane(e, lines=None):
    out = lines if lines is not None else e['output'].splitlines()
    rows = [('cmd', '$ ' + e['cmd'])]
    for l in out:
        for k, p in enumerate(textwrap.wrap(l, 150, drop_whitespace=False, replace_whitespace=False) or ['']):
            rows.append(('out', ('    ' if k else '') + p))
    return e['title'], rows
def render(panes, name):
    maxc = max(len(t) for _, rows in panes for _, t in rows)
    w = int(max(1800, CW * maxc + 70)); h = sum(54 + LH * len(rows) + 30 for _, rows in panes)
    img = Image.new('RGB', (w, h), (24, 26, 31)); d = ImageDraw.Draw(img); y = 0
    for ttl, rows in panes:
        d.rectangle([0, y, w, y + 50], fill=(50, 54, 62)); d.text((20, y + 9), ttl, fill=(225, 225, 225), font=MONO)
        yy = y + 70
        for kind, t in rows:
            d.text((28, yy), t, fill=(120, 220, 140) if kind == 'cmd' else (228, 228, 228), font=MONO); yy += LH
        y += 54 + LH * len(rows) + 30
    p = FIG / f'{name}.png'; img.save(p); return p

def split_even(lines, maxl=44):
    n = math.ceil(len(lines) / maxl); sz = math.ceil(len(lines) / n); return [lines[i:i + sz] for i in range(0, len(lines), sz)]

def fig_img(path, maxw=W, maxh=21.5 * cm, scale=0.26):
    iw, ih = Image.open(path).size; w = iw * scale; h = ih * scale
    f = min(1, maxw / w, maxh / h); return RLImage(str(path), width=w * f, height=h * f)

# ---------- document ----------
class Doc(BaseDocTemplate):
    def __init__(self, fn):
        BaseDocTemplate.__init__(self, fn, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
                                 title='Task 14: Kubernetes Scaling and Rolling Updates', author=ARGS.name,
                                 subject='Scaling, rolling updates, rollback and autoscaling on Kubernetes')
        self.addPageTemplates([PageTemplate(id='p', frames=[Frame(2 * cm, 2 * cm, W, A4[1] - 4 * cm, id='f', leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)])])
    def afterFlowable(self, fl):
        if hasattr(fl, 'toc_level'): self.notify('TOCEntry', (fl.toc_level, fl.toc_text, self.page))
class NumCanvas(pdfcanvas.Canvas):
    def __init__(self, *a, **k): pdfcanvas.Canvas.__init__(self, *a, **k); self._saved = []
    def showPage(self): self._saved.append(dict(self.__dict__)); self._startPage()
    def save(self):
        n = len(self._saved)
        for st in self._saved:
            self.__dict__.update(st)
            if self._pageNumber > 1:
                self.setFont('DV', 7.5); self.setFillColor(GREY); self.drawCentredString(A4[0] / 2, 1.1 * cm, f'{self._pageNumber} / {n}')
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)

S = []
def tbl(data, widths, header=True, label_col=False, zebra=False):
    rows = []
    for r, row in enumerate(data):
        rows.append([c if not isinstance(c, (str, int, float)) else P(str(c), cellh if (header and r == 0) else (cellb if (label_col and ci == 0) else cell)) for ci, c in enumerate(row)])
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [('GRID', (0, 0), (-1, -1), .5, LINE), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5), ('LEFTPADDING', (0, 0), (-1, -1), 7)]
    if header: st.append(('BACKGROUND', (0, 0), (-1, 0), NAVY))
    if label_col: st.append(('BACKGROUND', (0, 0), (0, -1), LGREY))
    if zebra: st += [('BACKGROUND', (0, r), (-1, r), colors.HexColor('#F6F8FB')) for r in range(2, len(data), 2)]
    t.setStyle(TableStyle(st)); return t


# ---------- charts (drawn from the measurements in evidence/results.json) ----------
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
def _style(ax):
    ax.grid(alpha=.25); ax.spines[['top', 'right']].set_visible(False)
def chart_versions(rows, name, title):
    if not rows: return None
    fig, ax = plt.subplots(figsize=(7.2, 3.1), dpi=200)
    ts = [r['t'] for r in rows]
    cols = {'ready': {'1.0': '#1F5FA8', '2.0': '#1E8E4E', '3.0': '#C0392B'}}
    for k in sorted({k for r in rows for k in r if k.startswith('v') and k.endswith('_ready')}):
        v = k[1:-6]; ax.step(ts, [r.get(k, 0) for r in rows], where='post', lw=2, color=cols['ready'].get(v, '#555'), label=f'version {v} ready')
    for k in sorted({k for r in rows for k in r if k.startswith('v') and k.endswith('_notready')}):
        if max(r.get(k, 0) for r in rows) > 0:
            v = k[1:-9]; ax.step(ts, [r.get(k, 0) for r in rows], where='post', lw=2, ls='--', color=cols['ready'].get(v, '#555'), label=f'version {v} NOT ready')
    ax.step(ts, [r.get('terminating', 0) for r in rows], where='post', lw=1.5, color='#999', label='terminating')
    ax.set_xlabel('time since start of the change (s)'); ax.set_ylabel('pods'); ax.set_title(title, fontsize=9, loc='left')
    ax.legend(fontsize=7, frameon=False, ncol=2); _style(ax); ax.set_ylim(bottom=0); ax.yaxis.get_major_locator().set_params(integer=True)
    p = FIG / f'{name}.png'; fig.tight_layout(); fig.savefig(p); plt.close(fig); return p
def chart_hpa(h):
    tl = h.get('timeline') or []
    if not tl: return None
    ts = [r['t'] for r in tl]
    fig, ax = plt.subplots(figsize=(7.2, 3.3), dpi=200)
    ax.step(ts, [r['pods'] for r in tl], where='post', lw=2, color='#1E8E4E', label='pods')
    ax.step(ts, [r['ready'] for r in tl], where='post', lw=1.4, color='#1F5FA8', ls='--', label='pods ready')
    ax.set_xlabel('time (s)'); ax.set_ylabel('replicas'); ax.set_ylim(0, max(h.get('max_replicas', 6), max(r['pods'] for r in tl)) + 1)
    ax.yaxis.get_major_locator().set_params(integer=True)
    ax2 = ax.twinx(); ax2.plot(ts, [r['cpu_util_pct'] if r['cpu_util_pct'] is not None else float('nan') for r in tl], color='#C0392B', lw=1.8, marker='o', ms=2.5, label='CPU utilisation of requests (%)')
    ax2.axhline(h.get('target_cpu_pct', 50), color='#C0392B', ls=':', lw=1); ax2.set_ylabel('CPU utilisation (% of request)')
    if h.get('load_seconds'): ax.axvspan(0, h['load_seconds'], color='#F5B041', alpha=.15, label='load applied')
    l1, n1 = ax.get_legend_handles_labels(); l2, n2 = ax2.get_legend_handles_labels()
    ax.legend(l1 + l2, n1 + n2, fontsize=7, frameon=False, loc='upper right'); ax.set_title('HorizontalPodAutoscaler: replicas and CPU utilisation (target 50 %)', fontsize=9, loc='left')
    _style(ax); p = FIG / 'hpa.png'; fig.tight_layout(); fig.savefig(p); plt.close(fig); return p

# ---------- figure plan (order = figure numbers; figures with no recorded output are skipped) ----------
BROWSER = EV / 'browser_app.png'
FIGS = [
 ('build', '6.1 Images and cluster', 'Tool versions, build of image scale-app:1.0 (last lines) and the images 1.0, 2.0 and the faulty 3.0 that were built from the same Dockerfile.', ['Tool versions', 'Build image 1.0', 'Docker images']),
 ('cluster', None, 'Creation of the three-node Kind cluster task14 (host port 8100 mapped to NodePort 30100), context, node readiness and node list.', ['List kind clusters', 'Create Kind cluster', 'Set kubectl context', 'Wait for all nodes Ready', 'Cluster nodes']),
 ('load', None, 'The three images loaded into the Kind nodes and metrics-server installed and patched (needed for kubectl top and the autoscaler).', ['Load image 1.0', 'Load image 2.0', 'Load image 3.0', 'Install metrics-server', 'Patch metrics-server', 'Wait for metrics-server']),
 ('deploy', '6.2 Initial deployment', 'Manifests applied, the initial 3-replica rollout, pods, Deployment, Service and EndpointSlice, and a first request to the application.', ['Apply manifests', 'Wait for initial rollout', 'Get pods (initial)', 'Get deployment and service', 'Application reachable']),
 ('scale', '6.3 Scaling replicas', 'Manual scaling 3 → 6 → 2 → 3 with kubectl scale; each step shows the time until every pod is Ready and the resulting pod list.', ['Scale 3 to 6', 'Scale 6 to 2', 'Scale 2 to 3']),
 ('update', '6.4 Rolling update', 'Rolling update from version 1.0 to 2.0: command and rollout progress, revision history (with change-cause) and the two ReplicaSets.', ['Rolling update to 2.0', 'Rollout history', 'ReplicaSets after update']),
 ('avail', None, 'Availability measured by a probe sending 10 requests per second through the Service during the rolling update, and the pod-state timeline sampled every 1.5 s.', ['Availability during rolling update', 'Version transition timeline']),
 ('bad', '6.5 Faulty release and rollback', 'Faulty release 3.0 (never ready): the rollout stalls, new pods stay 0/1 Ready, the Deployment reports the stalled progress.', ['Faulty release 3.0', 'Pods during failed rollout', 'Deployment conditions']),
 ('undo', None, 'Rollback with kubectl rollout undo, pods and history afterwards, and the availability measured throughout.', ['Rollback with rollout undo', 'Pods after rollback', 'Rollout history after rollback', 'Availability during faulty release']),
 ('base', '6.6 Resource utilisation and autoscaling', 'Baseline CPU/memory of pods and nodes (metrics-server) and creation of the HorizontalPodAutoscaler (3–6 pods, 50 % CPU target).', ['Pod resource usage (baseline)', 'Node resource usage (baseline)', 'Apply HPA']),
 ('hpaload', None, 'Resource usage and autoscaler status while CPU load is applied.', ['Pod resource usage (under load)', 'HPA status (under load)', 'Node resource usage (under load)']),
 ('hpaafter', None, 'Autoscaler status after the load stopped, pods after scale-down and availability during the whole autoscaling experiment.', ['HPA status (after load)', 'Pods after autoscaling', 'Availability during autoscaling']),
 ('hpadesc', None, 'kubectl describe hpa: conditions and the scaling events recorded by the autoscaler.', ['Describe HPA']),
 ('desc', '6.7 Monitoring deployment status', 'kubectl describe deployment web at the end of the run: strategy, probes, resources, conditions and ReplicaSets.', ['Deployment details']),
 ('events', None, 'Namespace events of the whole run (scheduling, scaling, probe failures of the faulty release, autoscaler decisions).', ['Recent events']),
 ('browser', None, 'The application opened in a browser at http://localhost:8100 (the colour and the version number identify the release).', 'browser'),
]
def have(spec): return (spec == 'browser' and BROWSER.exists()) or (isinstance(spec, list) and any(E(p) for p in spec))
FIGS = [f for f in FIGS if have(f[3])]
ru, bd, hp = RES.get('rolling_update', {}), RES.get('bad_release', {}), RES.get('hpa', {})
CH = [('c_update', 'Rolling update: ready pods per version over time (maxSurge 1, maxUnavailable 0).', chart_versions(ru.get('timeline'), 'c_update', 'Rolling update 1.0 → 2.0')),
      ('c_bad', 'Faulty release 3.0 and rollback: the new pods never become ready, the old pods keep serving until the rollback.', chart_versions(bd.get('timeline'), 'c_bad', 'Faulty release 3.0 and rollback to 2.0')),
      ('c_hpa', 'Autoscaling under load: replica count and CPU utilisation over time.', chart_hpa(hp))]
CH = [c for c in CH if c[2]]
FN = {k: i + 1 for i, k in enumerate([f[0] for f in FIGS] + [c[0] for c in CH])}
def F(k): return f'Figure {FN[k]}' if k in FN else 'the corresponding figure'

# ---------- derived numbers ----------
def S_(d): return d.get('summary', {}) if d else {}
su, sb, sh_ = S_(ru), S_(bd), S_(hp)
scal = RES.get('scaling', [])
hl = hp.get('timeline', [])
peak_pods = hp.get('peak_pods'); peak_cpu = max([r['cpu_util_pct'] for r in hl if r.get('cpu_util_pct') is not None] or [None]) if hl else None
first_up = next((r['t'] for r in hl if (r.get('pods') or 0) > hp.get('min_replicas', 3)), None)
reach_peak = next((r['t'] for r in hl if r.get('pods') == peak_pods), None) if peak_pods else None
back_to_min = next((r['t'] for r in hl if r.get('phase') == 'cooldown' and (r.get('pods') or 99) <= hp.get('min_replicas', 3)), None)
m = re.search(r'CreationTimestamp:\s+\w+, (\d+ \w+ \d{4})', OUTP('Deployment details'))
run_date = m.group(1) if m else datetime.date.today().strftime('%d %B %Y')
def pct(x): return f'{x}%' if x is not None else 'n/a'

S = []
def tbl(data, widths, header=True, label_col=False, zebra=False):
    rows = []
    for r, row in enumerate(data):
        rows.append([c if not isinstance(c, (str, int, float)) else P(str(c), cellh if (header and r == 0) else (cellb if (label_col and ci == 0) else cell)) for ci, c in enumerate(row)])
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    st = [('GRID', (0, 0), (-1, -1), .5, LINE), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5), ('LEFTPADDING', (0, 0), (-1, -1), 7)]
    if header: st.append(('BACKGROUND', (0, 0), (-1, 0), NAVY))
    if label_col: st.append(('BACKGROUND', (0, 0), (0, -1), LGREY))
    if zebra: st += [('BACKGROUND', (0, r), (-1, r), colors.HexColor('#F6F8FB')) for r in range(2, len(data), 2)]
    t.setStyle(TableStyle(st)); return t

# ===== Title page =====
S += [Spacer(1, 3.2 * cm), P('Task 14: Kubernetes Scaling and Rolling Updates', title),
      P('Manual Scaling, a Rolling Update Measured for Availability, Rollback of a Faulty Release and CPU-Based Autoscaling with Resource Monitoring', subtitle)]
rows = [['Student Name', ARGS.name], ['Class', ARGS.cls], ['Student ID', ARGS.id],
    ['Tools', f'Kubernetes on Kind, kubectl, metrics-server, HorizontalPodAutoscaler, Docker, Python automation ({code("deploy_scaling.py")})'],
    ['Application', f'Versioned Flask service {code("scale-app")} (1.0, 2.0 and a deliberately faulty 3.0) with a CPU-burning endpoint for load tests'],
    ['Cluster', f'{code("task14")}: 1 control-plane + 2 worker nodes; NodePort 30100 → {code("http://localhost:8100")}'],
    ['Experiments', 'Manual scaling 3→6→2→3 · rolling update 1.0→2.0 · faulty release 3.0 and rollback · autoscaling 3–6 pods under load'],
    ['Key Results', (f'Rolling update: {su.get("failed", "?")} failed of {su.get("requests", "?")} requests ({su.get("availability_pct", "?")} % available); ' if su else '') +
                    (f'autoscaler peak {peak_pods} pods' if peak_pods else 'see Section 7')],
    ['Run Date', run_date]]
if ARGS.github: rows.append(['GitHub Repository', f'<link href="{ARGS.github}" color="#1F3A9B">{ARGS.github}</link>'])
S.append(tbl(rows, [5.2 * cm, W - 5.2 * cm], header=False, label_col=True)); S.append(PageBreak())

# ===== Contents =====
S.append(H1('Contents')); del S[-1].toc_level
toc = TableOfContents(); toc.dotsMinLevel = 0
toc.levelStyles = [ParagraphStyle('t0', fontName='DV-B', fontSize=9, leading=11.6, leftIndent=0, firstLineIndent=0, textColor=colors.HexColor('#222222')),
                   ParagraphStyle('t1', fontName='DV', fontSize=7.6, leading=9.6, leftIndent=14, firstLineIndent=0, textColor=colors.HexColor('#333333'))]
S += [Spacer(1, 6), toc, PageBreak()]

# ===== 1-3 =====
S += [H1('1. Objective'),
      P('To implement scalability and deployment-update strategies with Kubernetes: scale the replicas of an application up and down, roll out a new version without interrupting service, monitor the deployment while it changes, validate that the application stays available, and analyse the resource utilisation that drives automatic scaling.'),
      H1('2. Reference Tools'),
      P(f'<b>Kubernetes</b> (on a three-node <b>Kind</b> cluster) provides the Deployment controller, ReplicaSets, the rolling-update strategy and the <b>HorizontalPodAutoscaler</b> (HPA). <b>metrics-server</b> supplies the CPU and memory metrics used by {code("kubectl top")} and by the HPA. The workload is a small Flask service, {code("scale-app")}, built three times from one Dockerfile: version 1.0 (initial), 2.0 (update) and 3.0 (a faulty release whose readiness endpoint always fails). A Python script drives every experiment and, in parallel, measures availability with a probe that sends ten requests per second through the Service.'),
      H1('3. Approach'),
      P(f'<b>1. Scale application replicas</b> — manual scaling 3 → 6 → 2 → 3 with {code("kubectl scale")}, timing how long all pods need to become Ready ({F("scale")}); automatic scaling with an HPA under CPU load ({F("hpaload")}).', num),
      P(f'<b>2. Perform rolling updates</b> — update the image from 1.0 to 2.0 with maxSurge 1 / maxUnavailable 0, then try a faulty 3.0 release and roll it back ({F("update")}, {F("bad")}, {F("undo")}).', num),
      P(f'<b>3. Monitor deployment status</b> — rollout status and history, ReplicaSets, pod timelines sampled every 1.5 s, describe output and events ({F("update")}, {F("avail")}, {F("desc")}).', num),
      P(f'<b>4. Validate application availability</b> — a continuous probe through the NodePort Service records every response (status, version, pod, latency) during the update, the faulty release and the autoscaling ({F("avail")}).', num),
      P(f'<b>5. Analyse resource utilisation</b> — {code("kubectl top")} for pods and nodes before and during load, and the HPA\'s CPU-utilisation / replica timeline ({F("base")}, {F("hpaload")}).', num),
      P(f'Everything is automated by {code("deploy_scaling.py")}; commands and outputs are stored in {code("evidence/run_log.json")} and all measurements in {code("evidence/results.json")}, from which this report is generated.')]

# ===== 4 Architecture =====
S += [H1('4. Architecture'),
      P('One Deployment (web) behind one NodePort Service. The Deployment owns one ReplicaSet per version; the HPA adjusts its replica count from metrics-server data; an external probe and load generator talk to the application through the Service.')]
S.append(H2('4.1 Project files'))
S.append(tbl([['File', 'Role'],
    [code('app14/app.py'), 'Versioned Flask service: /, /version, /health (liveness), /ready (readiness; always fails in the faulty release) and /work?ms=N (burns CPU).'],
    [code('app14/Dockerfile'), 'One Dockerfile, three images via build arguments VERSION and BROKEN; dependencies are installed before the arguments so layers are cached.'],
    [code('kind-config-task14.yaml'), 'Cluster with one control-plane and two workers; host port 8100 mapped to NodePort 30100.'],
    [code('k8s14/*.yaml'), 'Namespace scale-demo, Deployment web (3 replicas, RollingUpdate, probes, requests/limits) and NodePort Service web.'],
    [code('k8s14/optional/hpa.yaml'), 'HorizontalPodAutoscaler: 3–6 pods, 50 % CPU of the request, quick scale-up and a 30 s scale-down window.'],
    [code('deploy_scaling.py'), 'Automation, load generation, availability probe and measurement of all experiments.'],
    [code('Task14_Scaling_RollingUpdates.ipynb'), 'Notebook with the same commands (alternative to the .py script).']], [6.4 * cm, W - 6.4 * cm], zebra=True))
S.append(H2('4.2 Architecture'))
def diagram():
    H = 250; d = Drawing(W, H)
    def box(x, y, w, h, fill, stroke): d.add(Rect(x, y, w, h, rx=5, ry=5, fillColor=fill, strokeColor=stroke, strokeWidth=0.8))
    def txt(x, y, s, size=7, bold=False, anchor='middle', col=colors.HexColor('#1f2933')):
        d.add(String(x, y, s, fontName='DV-B' if bold else 'DV', fontSize=size, textAnchor=anchor, fillColor=col))
    def arrow(x1, y1, x2, y2):
        d.add(Line(x1, y1, x2, y2, strokeColor=BLUE, strokeWidth=1.3))
        d.add(Line(x2, y2, x2 - 3.5, y2 + 2.5, strokeColor=BLUE, strokeWidth=1.3)); d.add(Line(x2, y2, x2 - 3.5, y2 - 2.5, strokeColor=BLUE, strokeWidth=1.3))
    box(0, 0, W, H, colors.HexColor('#F7F9FC'), colors.HexColor('#C9D3E3'))
    txt(10, H - 16, 'macOS host  ·  Docker Desktop  ·  Kind cluster "task14"', 7.5, True, 'start', NAVY)
    box(10, H - 52, W - 20, 24, colors.HexColor('#EEF3FB'), colors.HexColor('#9FB4D8'))
    txt(W / 2, H - 38, 'Images scale-app:1.0 · 2.0 · 3.0 (faulty)  →  kind load  →  every node  ·  Deployment web: ReplicaSet per version', 6.6, True)
    NX, NY, NH, GAP = 108, 26, 160, 10
    NW = (W - 10 - NX - 2 * GAP) / 3; xs = [NX + i * (NW + GAP) for i in range(3)]
    for x, (n, r) in zip(xs, [('task14-control-plane', '(control-plane)'), ('task14-worker', '(worker)'), ('task14-worker2', '(worker)')]):
        box(x, NY, NW, NH, colors.white, colors.HexColor('#8FA3C4')); txt(x + NW / 2, NY + NH - 14, n, 6.8, True); txt(x + NW / 2, NY + NH - 24, r, 6.3, False, 'middle', GREY)
    box(10, 112, 88, 54, colors.white, BLUE); txt(54, 152, 'Probe + load', 7, True); txt(54, 141, 'generator (Python)', 6.6); txt(54, 130, 'localhost:8100', 6.6)
    box(10, NY + 4, 88, 74, colors.HexColor('#FFF6E5'), colors.HexColor('#E3B25C'))
    for i, (t, b) in enumerate([('Service web', True), ('NodePort 80:30100', False), ('selector app=web', False), ('Namespace scale-demo', False)]):
        txt(54, NY + 64 - i * 14, t, 6.4 if b else 6.1, b)
    for i, t in enumerate(['kube-apiserver', 'etcd · scheduler', 'Deployment + HPA ctrl.', 'metrics-server']):
        box(xs[0] + 8, NY + NH - 50 - i * 24, NW - 16, 18, colors.HexColor('#EAF1FB') if i < 3 else colors.HexColor('#FDECEA'), colors.HexColor('#B7C8E4') if i < 3 else colors.HexColor('#E3A6A0')); txt(xs[0] + NW / 2, NY + NH - 44 - i * 24, t, 6.3)
    txt(xs[0] + NW / 2, NY + 10, 'host 8100 → NodePort 30100', 5.9, False, 'middle', GREY)
    for x, k in [(xs[1], 2), (xs[2], 1)]:
        for i in range(k):
            box(x + 8, NY + NH - 54 - i * 32, NW - 16, 26, colors.HexColor('#E7F6EC'), colors.HexColor('#7DBB91'))
            txt(x + NW / 2, NY + NH - 40 - i * 32, 'web pod', 6.6, True); txt(x + NW / 2, NY + NH - 48 - i * 32, 'version 1.0 → 2.0 · 100m CPU', 5.6, False, 'middle', GREY)
    txt(xs[2] + NW / 2, NY + 30, 'HPA adds up to 3 more pods', 5.8, False, 'middle', GREY)
    arrow(98, 140, xs[0], 140); arrow(xs[0] + NW, 100, xs[1], 100); arrow(xs[1] + NW, 100, xs[2], 100)
    txt(W / 2, 11, 'Diagram 1: Components and request path (illustrative; pod placement and count change during the experiments).', 6.3, False, 'middle', GREY)
    return d
S += [diagram(), Spacer(1, 14), P('Requests enter through the host port mapping and the NodePort Service and are spread over the <b>ready</b> pods; pods that are not ready (new pods during an update, or a faulty release) receive no traffic. The HPA reads CPU usage from metrics-server and changes the Deployment\'s replica count; the Deployment controller then adds or removes pods.')]
S.append(H2('4.3 Scaling and update configuration'))
S.append(tbl([['Setting', 'Value', 'Purpose'],
    ['replicas', '3 (HPA range 3–6)', 'Baseline capacity; the autoscaler may add up to three pods.'],
    ['strategy', 'RollingUpdate · maxSurge 1 · maxUnavailable 0', 'One extra pod is started and must become ready before an old pod is removed, so capacity never drops.'],
    ['readinessProbe', 'GET /ready every 2 s', 'A new pod receives traffic only when its release is healthy; the faulty release never passes.'],
    ['livenessProbe', 'GET /health every 10 s', 'Restarts a hung process without being affected by readiness.'],
    ['progressDeadlineSeconds', '60', 'A stalled rollout is reported as failed after one minute.'],
    ['resources', 'requests 100m / 64Mi · limits 200m / 128Mi', 'Requests are the basis of the HPA\'s utilisation percentage; limits cap one pod at 200 % of its request.'],
    ['revisionHistoryLimit', '5', 'Old ReplicaSets are kept so that rollback is possible.'],
    ['HPA', 'target 50 % CPU · scale-up +3 pods/15 s · scale-down window 30 s', 'Fast reaction to load and a shortened (default 300 s) cool-down so the demo finishes.']], [3.7 * cm, 5.8 * cm, W - 9.5 * cm], zebra=True))
S.append(H2('4.4 Running the project'))
for i, c in enumerate(['python deploy_scaling.py        # about 15-20 minutes', 'python build_report.py --name "Your Name" --id "Your ID"'], 1):
    S.append(P(f'{i}. {code(c)}', num))
S.append(P(f'Prerequisites: Docker Desktop running, {code("kubectl")}, {code("kind")}, Python 3 with Pillow, ReportLab and Matplotlib, and internet access (base image, metrics-server manifest). While the script runs it prints live progress, including the autoscaler\'s replica count every few seconds.'))
S.append(H2('4.5 Measurement method'))
S.append(tbl([['Quantity', 'How it is measured'],
    ['Availability', f'A background thread requests {code("/version")} through the NodePort Service every 0.1 s (0.5 s during the load test); success means HTTP 200. Availability = successful / total requests.'],
    ['Latency', 'Time per successful request; p50, p95 and maximum are reported.'],
    ['Version transition', 'The probe records which version answered; a pod sampler records ready / not-ready / terminating pods per version every 1.5 s.'],
    ['Time to scale', f'Seconds from {code("kubectl scale")} until all desired pods are Ready.'],
    ['CPU utilisation', f'{code("kubectl top")} (millicores) and the HPA\'s currentMetrics (percent of the 100m request), sampled every ~9 s.']], [3.4 * cm, W - 3.4 * cm], zebra=True))
S.append(PageBreak())

# ===== 5 Source =====
DESC = {'app.py': 'versioned test service', 'Dockerfile': 'image definition (VERSION / BROKEN build arguments)', 'kind-config-task14.yaml': 'Kind cluster definition', '00-namespace.yaml': 'Namespace',
        '01-deployment.yaml': 'Deployment (rolling-update strategy)', '02-service.yaml': 'NodePort Service', 'hpa.yaml': 'HorizontalPodAutoscaler', 'deploy_scaling.py': 'experiment automation'}
NL = len((SRC / 'deploy_scaling.py').read_text().splitlines())
S += [H1('5. Source Code'), P(f'All files needed to reproduce the experiments are listed with line numbers: the application and image (5.1–5.2), the cluster and manifests (5.3–5.7) and the automation script (5.8, {NL} lines). Lines longer than 118 characters are wrapped and continued with "↳".')]
def listing(no, label, path, chunk=62):
    lines = Path(path).read_text().splitlines()
    for i in range(0, len(lines), chunk):
        part = lines[i:i + chunk]; rng = f' (lines {i+1}–{i+len(part)})' if len(lines) > chunk else ''
        S.append(KeepTogether([H2(f'{no} {code(label)} — {DESC[label]}{rng}'), CodeBlock(part, i + 1), Spacer(1, 4)]))
for no, label, path in [('5.1', 'app.py', 'app14/app.py'), ('5.2', 'Dockerfile', 'app14/Dockerfile'), ('5.3', 'kind-config-task14.yaml', 'kind-config-task14.yaml'), ('5.4', '00-namespace.yaml', 'k8s14/00-namespace.yaml'),
                        ('5.5', '01-deployment.yaml', 'k8s14/01-deployment.yaml'), ('5.6', '02-service.yaml', 'k8s14/02-service.yaml'), ('5.7', 'hpa.yaml', 'k8s14/optional/hpa.yaml'), ('5.8', 'deploy_scaling.py', 'deploy_scaling.py')]:
    listing(no, label, SRC / path)
S.append(PageBreak())

# ===== 6 Screenshots =====
S += [H1('6. Screenshots and Command Output'),
      P(f'Terminal figures show the exact output captured by {code("deploy_scaling.py")} during the run ({code("evidence/run_log.json")}), rendered in a terminal style rather than retyped. Charts in Section 7 are drawn from the measurements in {code("evidence/results.json")}. Pod names, IPs and timings are those of this particular run.')]
for key, sect, caption, spec in FIGS:
    n = FN[key]; blocks = []
    if sect: blocks.append(H2(sect))
    if spec == 'browser':
        im = Image.open(BROWSER).convert('RGB'); p = FIG / 'browser.png'; im.save(p)
        blocks += [fig_img(p, maxw=W, maxh=13 * cm, scale=1), P(f'Figure {n}: {caption}', cap)]
    else:
        ents = [E(pfx) for pfx in spec if E(pfx)]
        if len(ents) == 1 and len(ents[0]['output'].splitlines()) > 44:
            e = ents[0]; parts = split_even(e['output'].splitlines())
            for j, pl in enumerate(parts, 1):
                pth = render([pane(e, pl)], f'f{n}_{j}'); lbl = f' (part {j} of {len(parts)})'
                blk = [fig_img(pth, scale=0.26), P(f'Figure {n}{lbl}: {caption}' if j == 1 else f'Figure {n}{lbl}: continued.', cap)]
                if j < len(parts): S.append(KeepTogether(blocks + blk)); blocks = []
                else: blocks += blk
        else:
            pth = render([pane(e) for e in ents], f'f{n}'); blocks += [fig_img(pth, scale=0.26), P(f'Figure {n}: {caption}', cap)]
    S.append(KeepTogether(blocks))
S.append(PageBreak())

# ===== 7 Results =====
S += [H1('7. Results'), P(f'The tables and charts below are computed from the measurements recorded during the run. Mapping to the deliverables: <b>scaling documentation</b> — Sections 4 and 7.1; <b>monitoring screenshots</b> — Section 6 and the charts; <b>performance observations</b> — Sections 7 and 8.')]
S.append(H2('7.1 Scaling replicas'))
if scal:
    S.append(tbl([['Change', 'Time until all pods Ready', 'Observation']] + [[f'{r["from"]} → {r["to"]} replicas', f'{r["seconds_to_ready"]} s' if r['seconds_to_ready'] is not None else 'timeout',
        'Scale-up has to start containers and pass the readiness probe' if r['to'] > r['from'] else 'Scale-down removes surplus pods; no new containers are started'] for r in scal], [4 * cm, 4.4 * cm, W - 8.4 * cm], zebra=True))
    S.append(P('Scaling up is limited by container start-up and the readiness probe (period 2 s); scaling down only terminates pods and the remaining pods stay Ready, so it completes as soon as the extra pods are gone.', small))
S.append(H2('7.2 Rolling update 1.0 → 2.0'))
if su:
    S.append(tbl([['Metric', 'Value'], ['Update duration (set image → rollout complete)', f'{ru.get("duration_s")} s'], ['Probe requests sent', su['requests']], ['Failed requests', su['failed']],
                  ['Availability', f'{su["availability_pct"]} %'], ['Responses by version', ', '.join(f'{k}: {v}' for k, v in su['versions'].items())],
                  ['Latency p50 / p95 / max', f'{su["latency_ms"]["p50"]} / {su["latency_ms"]["p95"]} / {su["latency_ms"]["max"]} ms']], [8 * cm, W - 8 * cm], zebra=True))
tlu = ru.get('timeline') or []
if tlu:
    keys = sorted({k for r in tlu for k in r if k not in ('t', 'total')}); rows = []; last = None
    for r in tlu:
        sig = tuple(r.get(k, 0) for k in keys)
        if sig != last: rows.append(r); last = sig
    rows = rows[:16]
    S.append(Spacer(1, 6)); S.append(tbl([['t (s)'] + [k.replace('_', ' ') for k in keys]] + [[r['t']] + [r.get(k, 0) for k in keys] for r in rows], [1.6 * cm] + [(W - 1.6 * cm) / len(keys)] * len(keys), zebra=True))
    S.append(P('Pod states during the update (a row is shown whenever the state changed). With maxSurge 1 and maxUnavailable 0 the new pod must become ready before an old pod is terminated.', small))
for k, cp, p in CH:
    if k == 'c_update': S.append(KeepTogether([Spacer(1, 6), fig_img(p, scale=0.5), P(f'Figure {FN[k]}: {cp}', cap)]))
S.append(H2('7.3 Faulty release and rollback'))
if sb:
    v3r = max([r.get('v3.0_ready', 0) for r in bd.get('timeline', [])] or [0]); v3n = max([r.get('v3.0_notready', 0) for r in bd.get('timeline', [])] or [0])
    S.append(tbl([['Metric', 'Value'], ['Release 3.0 pods that became Ready', v3r], ['Release 3.0 pods stuck not-ready (maximum)', v3n], ['Rollout outcome', 'stalled / failed (progress deadline 60 s)' if bd.get('stalled') else 'see Figure'],
                  ['Rollback duration (rollout undo → complete)', f'{bd.get("rollback_s")} s'], ['Probe requests / failed', f'{sb["requests"]} / {sb["failed"]}'], ['Availability', f'{sb["availability_pct"]} %'],
                  ['Responses by version', ', '.join(f'{k}: {v}' for k, v in sb['versions'].items())]], [8 * cm, W - 8 * cm], zebra=True))
for k, cp, p in CH:
    if k == 'c_bad': S.append(KeepTogether([Spacer(1, 6), fig_img(p, scale=0.5), P(f'Figure {FN[k]}: {cp}', cap)]))
S.append(H2('7.4 Resource utilisation and autoscaling'))
if hl:
    S.append(tbl([['Metric', 'Value'], ['HPA configuration', 'min 3 · max 6 · target 50 % of the 100m CPU request'], ['Load applied for', f'{hp.get("load_seconds")} s (14 parallel clients, 100 ms of CPU work per request)'],
                  ['Peak CPU utilisation (% of request)', pct(peak_cpu)], ['Peak number of pods', peak_pods], ['First scale-up observed at', f'{first_up} s' if first_up is not None else 'not observed'],
                  ['Peak replica count reached at', f'{reach_peak} s' if reach_peak is not None else 'n/a'], ['Back at minimum replicas at', f'{back_to_min} s' if back_to_min is not None else 'not reached within the observation window'],
                  ['Availability during the experiment', f'{sh_.get("availability_pct")} % ({sh_.get("failed")} failed of {sh_.get("requests")})' if sh_ else 'n/a'],
                  ['Latency p50 / p95 / max', f'{sh_["latency_ms"]["p50"]} / {sh_["latency_ms"]["p95"]} / {sh_["latency_ms"]["max"]} ms' if sh_ else 'n/a']], [8 * cm, W - 8 * cm], zebra=True))
    step = max(1, len(hl) // 18); sel = hl[::step]
    S.append(Spacer(1, 6)); S.append(tbl([['t (s)', 'Phase', 'CPU % of request', 'HPA replicas (cur → desired)', 'Pods ready / total', 'Avg CPU / pod']] +
        [[r['t'], r['phase'], pct(r['cpu_util_pct']), f'{r["hpa_current"]} → {r["hpa_desired"]}', f'{r["ready"]} / {r["pods"]}', f'{r["avg_cpu_m"]}m' if r['avg_cpu_m'] is not None else 'n/a'] for r in sel],
        [1.5 * cm, 2.0 * cm, 3 * cm, 4.2 * cm, 3.3 * cm, W - 14 * cm], zebra=True))
for k, cp, p in CH:
    if k == 'c_hpa': S.append(KeepTogether([Spacer(1, 6), fig_img(p, scale=0.5), P(f'Figure {FN[k]}: {cp}', cap)]))
S.append(H2('7.5 Evaluation criteria'))
ok_up = bool(scal) and all(r['seconds_to_ready'] is not None for r in scal)
ok_ru = bool(su) and su['failed'] == 0 and len(su['versions']) >= 2
ok_st = bool(sb) and sb['failed'] == 0 and set(sb['versions']) <= {'2.0'}
S.append(tbl([['Criterion', 'Evidence', 'Status'],
    ['Scaling effectiveness', f'Manual scaling reached every target (slowest: {max(r["seconds_to_ready"] or 0 for r in scal)} s); the HPA grew the Deployment to {peak_pods} pods under load and back to the minimum afterwards.' if hl else 'See Section 7.1.', 'Met' if ok_up and (not hl or (peak_pods or 0) > 3) else 'Check'],
    ['Rolling update implementation', f'Version 2.0 replaced 1.0 pod by pod; {su.get("failed")} of {su.get("requests")} requests failed; both versions served during the transition.' if su else 'See Section 7.2.', 'Met' if ok_ru else 'Check'],
    ['System stability', f'The faulty release never received traffic ({sb.get("failed")} failed requests), the rollout stalled instead of removing healthy pods, and rollout undo restored version 2.0; availability under load was {sh_.get("availability_pct")} %.' if sb and sh_ else 'See Sections 7.3–7.4.', 'Met' if ok_st else 'Check']], [4.2 * cm, W - 6.2 * cm, 2 * cm], zebra=True))
S.append(Spacer(1, 6))

# ===== 8-10 =====
vers = ', '.join(f'{k}: {v}' for k, v in su.get('versions', {}).items()) if su else ''
S += [H1('8. Observations'),
      P(f'<b>Scaling up is bounded by start-up, scaling down is immediate.</b> ' + (f'Scaling {scal[0]["from"]} → {scal[0]["to"]} took {scal[0]["seconds_to_ready"]} s (new containers must start and pass readiness); scaling {scal[1]["from"]} → {scal[1]["to"]} took {scal[1]["seconds_to_ready"]} s.' if len(scal) > 1 else 'See Section 7.1.'), bullet),
      P(f'<b>maxUnavailable 0 keeps capacity constant.</b> ' + (f'During the rolling update the probe saw {su["failed"]} failures in {su["requests"]} requests and responses from both versions ({vers}); the pod timeline (Section 7.2) shows how the new pods replaced the old ones.' if su else ''), bullet),
      P(f'<b>Readiness gates protect users from a bad release.</b> ' + (f'Release 3.0 never became ready, so it received no traffic; the probe still recorded {sb["availability_pct"]} % availability while the rollout was stalled and during the rollback ({bd.get("rollback_s")} s).' if sb else ''), bullet),
      P(f'<b>Rollback is a controller operation, not a rebuild.</b> {code("kubectl rollout undo")} re-activated the previous ReplicaSet, which Kubernetes keeps for exactly this purpose (revisionHistoryLimit 5).', bullet),
      P(f'<b>The HPA scales on measured CPU, not instantly.</b> ' + (f'CPU utilisation peaked at {pct(peak_cpu)} of the request against a 50 % target; the first extra pod appeared at {first_up} s and {peak_pods} pods were running at the peak.' if hl and first_up is not None else 'See Section 7.4.'), bullet),
      P(f'<b>Scale-down is deliberately slower.</b> ' + (f'After the load stopped the replica count returned to the minimum at {back_to_min} s (scale-down stabilisation window shortened to 30 s; the default is 300 s).' if back_to_min is not None else 'The scale-down window (30 s here, default 300 s) delays the return to the minimum replica count.'), bullet),
      P(f'<b>Requests, not limits, drive autoscaling.</b> The utilisation percentage is relative to the 100m request, so a pod limited to 200m can show up to 200 %; choosing realistic requests is essential for sensible HPA behaviour.', bullet),
      P('<b>Latency under load.</b> ' + (f'The probe measured p50 {sh_["latency_ms"]["p50"]} ms and p95 {sh_["latency_ms"]["p95"]} ms (maximum {sh_["latency_ms"]["max"]} ms) while the pods were CPU-bound, compared with {su["latency_ms"]["p50"]} ms p50 during the quiet rolling update.' if sh_ and su else 'See Section 7.4.'), bullet),
      H1('9. Known Limitations'),
      P('• <b>Single machine.</b> All nodes share one laptop\'s CPU, so measured CPU and latency also depend on what else the machine is doing; absolute numbers are indicative.', bullet),
      P('• <b>Synthetic workload.</b> /work burns CPU for a fixed time; real applications may be memory- or I/O-bound and need other metrics (custom or external metrics).', bullet),
      P('• <b>Shortened HPA cool-down.</b> The 30 s scale-down window is for demonstration; production setups usually keep minutes to avoid flapping.', bullet),
      P('• <b>Probe via NodePort and host port mapping.</b> Measurements include Docker Desktop\'s network path, not only Kubernetes.', bullet),
      P('• <b>No cluster autoscaling.</b> Only pods are scaled; the number of nodes is fixed.', bullet),
      H1('10. Conclusion'),
      P('Kubernetes scaled the application manually and automatically, replaced version 1.0 by 2.0 without interrupting service, contained a faulty 3.0 release through readiness probes and the rolling-update strategy, and restored the previous version with one command. Continuous probing quantified availability and latency in every experiment, and metrics-server data explained the autoscaler\'s decisions. The deliverables are the scaling documentation (Sections 4 and 7), the monitoring screenshots (Section 6) and the performance observations (Sections 7 and 8).')]

Doc(str(OUT)).multiBuild(S, canvasmaker=NumCanvas)
print('Created', OUT)
