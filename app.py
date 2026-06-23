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
    try:
        s = turso_query("SELECT * FROM summary WHERE id=1")
        if s:
            summary = s[0]
        clients = turso_query("SELECT * FROM clients ORDER BY owed DESC")
    except Exception as e:
        summary = {"error": str(e)}
    return summary, clients


@app.route("/api/summary")
def api_summary():
    if API_KEY and request.args.get("key", "") != API_KEY:
        return jsonify({"error": "unauthorized"}), 401
    summary, clients = fetch_data()
    return jsonify({"summary": summary, "clients": clients})


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/")
def index():
    summary, clients = fetch_data()
    return Response(render_page(summary, clients), mimetype="text/html")


def vnd(n):
    try:
        return "{:,.0f}".format(float(n or 0)).replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def render_page(s, clients):
    if s.get("error"):
        body = ('<div class="err">Lỗi đọc Turso: ' + str(s["error"]) +
                '<br><small>Kiểm tra TURSO_URL / TURSO_TOKEN trên Render.</small></div>')
    else:
        owed = s.get("owed_money", 0)
        rows = ""
        for c in clients:
            col = "#fb7185" if (c.get("owed", 0) or 0) > 0 else "#34d399"
            txt = ("nợ " + vnd(c["owed"])) if (c.get("owed", 0) or 0) > 0 else "đủ"
            rows += (
                '<div class="cli"><div class="cn">' + str(c.get("client", "")) + '</div>'
                '<div class="cm">' + str(c.get("cases", 0)) + ' ca · ' + str(c.get("units", 0)) + ' đv</div>'
                '<div class="cd" style="color:' + col + '">' + txt + '</div></div>')
        body = (
            '<div class="strip">'
            '<div class="st"><b>' + str(s.get("total_cases", 0)) + '</b><span>ca tháng</span></div>'
            '<div class="st"><b>' + str(s.get("total_units", 0)) + '</b><span>đơn vị</span></div>'
            '<div class="st"><b class="o">' + str(s.get("today_cases", 0)) + '</b><span>ca hôm nay</span></div>'
            '<div class="st"><b class="o">' + str(s.get("today_units", 0)) + '</b><span>đv hôm nay</span></div>'
            '</div>'
            '<div class="strip">'
            '<div class="st"><b class="b">' + vnd(s.get("total_money")) + '</b><span>tổng tiền</span></div>'
            '<div class="st"><b class="g">' + vnd(s.get("paid_money")) + '</b><span>đã thu</span></div>'
            '<div class="st"><b class="y">' + vnd(owed) + '</b><span>còn nợ</span></div>'
            '</div>'
            '<div class="lbl">Công nợ theo khách</div>'
            '<div class="clis">' + (rows or '<div class="muted">Chưa có dữ liệu</div>') + '</div>'
            '<div class="upd">Cập nhật: ' + str(s.get("updated_at", "—")) + ' · tháng ' + str(s.get("month", "")) + '</div>')
    return """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="120">
<title>PainLAB · Sản lượng</title>
<style>
*{box-sizing:border-box;margin:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#140c1f;color:#e9e2f5;padding:18px;max-width:760px;margin:auto}
h1{font-size:20px;margin-bottom:16px;color:#c4b5fd}
.strip{display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap}
.st{flex:1;min-width:120px;background:#1e1330;border:1px solid #2e2042;border-radius:14px;padding:16px;text-align:center}
.st b{display:block;font-size:26px;font-weight:900;color:#c4b5fd}
.st b.o{color:#fb923c}.st b.b{color:#93c5fd}.st b.g{color:#6ee7b7}.st b.y{color:#fbbf24}
.st span{font-size:11px;color:#9d8fb8;text-transform:uppercase;letter-spacing:.5px}
.lbl{font-size:12px;color:#9d8fb8;text-transform:uppercase;letter-spacing:.6px;margin:18px 2px 10px}
.clis{display:flex;flex-direction:column;gap:8px}
.cli{display:flex;align-items:center;gap:12px;background:#1a1029;border:1px solid #2e2042;border-radius:12px;padding:12px 16px}
.cli .cn{font-weight:800;font-size:15px;min-width:60px}
.cli .cm{font-size:12px;color:#9d8fb8;flex:1}
.cli .cd{font-weight:900;font-size:14px}
.upd{margin-top:18px;font-size:11px;color:#6b5d80;text-align:center}
.err{background:#2a1320;border:1px solid #5a2030;border-radius:12px;padding:18px;color:#fb7185}
.muted{color:#6b5d80;padding:14px}
</style></head><body><h1>📊 PainLAB · Sản lượng</h1>""" + body + "</body></html>"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
