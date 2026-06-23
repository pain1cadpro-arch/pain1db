# -*- coding: utf-8 -*-
"""
DentalMatcher Cloud — web service (Render.com).
Doc tom tat san luong tu Turso, hien dashboard + JSON API cho widget iPhone.

Bien moi truong (Render → Environment):
  TURSO_URL    = libsql://dental-xxxx.turso.io  (hoac https://...)
  TURSO_TOKEN  = <auth token quyen DOC>
  API_KEY      = <chuoi bi mat tuy chon> — neu dat, /api/summary can ?key=API_KEY
"""
import os, json, urllib.request, urllib.error
from flask import Flask, jsonify, request, Response

app = Flask(__name__)

TURSO_URL = os.environ.get("TURSO_URL", "").strip()
TURSO_TOKEN = os.environ.get("TURSO_TOKEN", "").strip()
API_KEY = os.environ.get("API_KEY", "").strip()


def _http_base(url):
    base = url.rstrip("/")
    for pre in ("libsql://", "wss://", "ws://"):
        if base.startswith(pre):
            return "https://" + base[len(pre):]
    if not base.startswith("http"):
        return "https://" + base
    return base


def turso_query(sql, args=None):
    """Chay 1 cau SELECT, tra ve list[dict]."""
    if not TURSO_URL or not TURSO_TOKEN:
        raise RuntimeError("Chua cau hinh TURSO_URL / TURSO_TOKEN")
    stmt = {"sql": sql}
    if args:
        stmt["args"] = args
    body = json.dumps({"requests": [
        {"type": "execute", "stmt": stmt},
        {"type": "close"},
    ]}).encode("utf-8")
    req = urllib.request.Request(_http_base(TURSO_URL) + "/v2/pipeline", data=body, headers={
        "Authorization": "Bearer " + TURSO_TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    res = data.get("results", [{}])[0]
    if res.get("type") == "error":
        raise RuntimeError(res.get("error", {}).get("message", "Turso error"))
    result = res.get("response", {}).get("result", {})
    cols = [c["name"] for c in result.get("cols", [])]
    rows = []
    for raw in result.get("rows", []):
        d = {}
        for name, cell in zip(cols, raw):
            v = cell.get("value")
            if cell.get("type") == "integer" and v is not None:
                try: v = int(v)
                except (TypeError, ValueError): pass
            elif cell.get("type") == "float" and v is not None:
                try: v = float(v)
                except (TypeError, ValueError): pass
            elif cell.get("type") == "null":
                v = None
            d[name] = v
        rows.append(d)
    return rows


def fetch_data():
    summary = {}
    clients = []
    cases = []
    try:
        s = turso_query("SELECT * FROM summary WHERE id=1")
        if s:
            summary = s[0]
        clients = turso_query("SELECT * FROM clients ORDER BY owed DESC")
        try:
            cases = turso_query("SELECT * FROM cases ORDER BY ts DESC")
        except Exception:
            cases = []  # bang cases co the chua ton tai (chua day ban moi)
    except Exception as e:
        summary = {"error": str(e)}
    return summary, clients, cases


@app.route("/api/summary")
def api_summary():
    if API_KEY and request.args.get("key", "") != API_KEY:
        return jsonify({"error": "unauthorized"}), 401
    summary, clients, cases = fetch_data()
    return jsonify({"summary": summary, "clients": clients, "cases": cases})


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/")
def index():
    summary, clients, cases = fetch_data()
    return Response(render_page(summary, cases), mimetype="text/html")


def vnd(n):
    try:
        return "{:,.0f}".format(float(n or 0)).replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def esc(x):
    return (str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_page(s, cases):
    if s.get("error"):
        return _shell(
            '<div class="err">Lỗi đọc Turso: ' + esc(s["error"]) +
            '<br><small>Kiểm tra TURSO_URL / TURSO_TOKEN trên Render.</small></div>', "—")

    cards = (
        '<section class="summary">'
        '<div class="card violet"><span>Ca tháng</span><strong>' + str(s.get("total_cases", 0)) + '</strong></div>'
        '<div class="card blue"><span>Đơn vị tháng</span><strong>' + str(s.get("total_units", 0)) + '</strong></div>'
        '<div class="card orange hl"><span>Ca hôm nay</span><strong>' + str(s.get("today_cases", 0)) + '</strong></div>'
        '<div class="card orange hl"><span>Đơn vị hôm nay</span><strong>' + str(s.get("today_units", 0)) + '</strong></div>'
        '</section>')

    rows = ""
    for c in cases:
        nm = esc(c.get("name", ""))
        cli = esc(c.get("client", ""))
        units = c.get("units", 0)
        date = esc(c.get("date", ""))
        model = '<span class="pill model">MODEL</span>' if c.get("model") else ''
        search = (str(c.get("name", "")) + " " + str(c.get("client", ""))).lower().replace('"', "")
        rows += (
            '<div class="case-row" data-s="' + esc(search) + '">'
            '<div class="row-top"><span class="pill cli">' + cli + '</span>'
            '<span class="date">' + date + '</span></div>'
            '<h3>' + nm + '</h3>'
            '<div class="case-meta"><span class="pill u">' + str(units) + ' đv</span>' + model + '</div>'
            '</div>')
    if not rows:
        rows = ('<div class="empty">Chưa có danh sách ca. Trên app desktop bấm '
                '<b>☁ Đẩy lên cloud</b> (bản mới) để hiện ca mới hoàn thành.</div>')

    panel = (
        '<section class="panel">'
        '<div class="panel-title"><h2>Ca mới hoàn thành</h2>'
        '<input id="q" type="search" placeholder="Tìm mã ca, khách…"></div>'
        '<div id="list" class="case-list">' + rows + '</div></section>')

    return _shell(cards + panel, s.get("updated_at", "—"), s.get("month", ""))


def _shell(body, updated, month=""):
    return """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta http-equiv="refresh" content="120">
<meta name="theme-color" content="#f5f3ff">
<title>PainLAB · Sản lượng</title>
<style>
:root{font-family:Inter,'Segoe UI',-apple-system,system-ui,sans-serif;
 --accent:#7c3aed;--muted:#6b7280;--soft:#374151;--border:#e6e1f2;--card:rgba(255,255,255,.92)}
*{box-sizing:border-box;margin:0}
body{min-height:100vh;color:#1c1530;
 background:radial-gradient(circle at 12% 0%,rgba(124,58,237,.13),transparent 36%),
 linear-gradient(180deg,#fbfaff 0%,#f1ecfb 100%)}
h1,h2,h3,p{margin:0}
header{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;
 gap:14px;padding:max(18px,env(safe-area-inset-top)) 18px 16px;background:rgba(255,255,255,.82);
 border-bottom:1px solid rgba(230,225,242,.9);backdrop-filter:blur(22px) saturate(130%)}
.eyebrow{color:var(--accent);font-size:11px;font-weight:800;letter-spacing:.18em;text-transform:uppercase}
h1{font-size:25px;line-height:1.05;letter-spacing:-.03em}
#status{color:var(--muted);font-size:12px;white-space:nowrap;text-align:right}
main{padding:18px 14px calc(28px + env(safe-area-inset-bottom));max-width:960px;margin:auto}
.summary{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.card,.panel,.case-row{border:1px solid var(--border);border-radius:24px;background:var(--card);
 box-shadow:0 18px 42px rgba(28,21,48,.08);backdrop-filter:blur(20px) saturate(125%)}
.card{min-height:118px;padding:18px;display:flex;flex-direction:column;justify-content:space-between}
.card span{color:var(--muted);font-size:12px;letter-spacing:.04em;text-transform:uppercase;font-weight:600}
.card strong{font-size:40px;line-height:1;color:#1c1530;font-weight:800}
.card.violet{border-color:rgba(124,58,237,.28)}.card.violet strong{color:#6d28d9}
.card.blue{border-color:rgba(59,130,246,.26)}.card.blue strong{color:#1d4ed8}
.card.orange{border-color:rgba(245,158,11,.32)}.card.orange strong{color:#c2570c}
.card.hl{background:linear-gradient(180deg,rgba(255,247,237,.95),rgba(255,255,255,.92))}
.panel{margin-top:16px;padding:18px}
.panel-title{display:grid;gap:10px;margin-bottom:14px}
h2{font-size:18px}
input[type=search]{width:100%;padding:13px 14px;color:#1c1530;background:#fff;
 border:1px solid var(--border);border-radius:16px;font-size:16px}
input[type=search]:focus{outline:none;border-color:rgba(124,58,237,.55);box-shadow:0 0 0 3px rgba(124,58,237,.12)}
.case-list{display:grid;gap:12px}
.case-row{padding:16px;transition:transform .15s,border-color .15s,background .15s}
.case-row:hover{border-color:rgba(124,58,237,.45);background:rgba(245,243,255,.96)}
.row-top{display:flex;align-items:center;justify-content:space-between;gap:10px}
.case-row h3{margin-top:9px;font-size:19px;color:#1c1530;word-break:break-word}
.case-meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px}
.date{color:var(--muted);font-size:12px;font-weight:600;white-space:nowrap}
.pill{padding:6px 11px;border-radius:11px;font-size:12px;font-weight:700;white-space:nowrap}
.pill.cli{color:#5b21b6;background:#f3e8ff;border:1px solid rgba(124,58,237,.28)}
.pill.u{color:#075985;background:#e0f2fe;border:1px solid rgba(56,189,248,.34)}
.pill.model{color:#9a3412;background:#ffedd5;border:1px solid rgba(245,158,11,.4)}
.empty{color:var(--muted);padding:18px 4px;font-size:14px;line-height:1.6}
.err{margin:18px;padding:18px;color:#b91c1c;background:#fef2f2;border:1px solid #fecaca;border-radius:18px}
@media(min-width:700px){.summary{grid-template-columns:repeat(4,1fr)}}
</style></head><body>
<header><div><p class="eyebrow">PainLAB</p><h1>Tổng quan sản lượng</h1></div>
<span id="status">Cập nhật """ + esc(updated) + ("" if not month else " · " + esc(month)) + """</span></header>
<main>""" + body + """</main>
<script>
const q=document.getElementById('q');
if(q){q.addEventListener('input',()=>{const v=q.value.toLowerCase().trim();
 document.querySelectorAll('.case-row').forEach(r=>{
   r.style.display=(!v||r.dataset.s.includes(v))?'':'none';});});}
</script>
</body></html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
