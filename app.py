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
    days = []
    try:
        s = turso_query("SELECT * FROM summary WHERE id=1")
        if s:
            summary = s[0]
        clients = turso_query("SELECT * FROM clients ORDER BY owed DESC")
        try:
            cases = turso_query("SELECT * FROM cases ORDER BY ts DESC")
        except Exception:
            cases = []
        try:
            days = turso_query("SELECT * FROM days ORDER BY day ASC")
        except Exception:
            days = []
    except Exception as e:
        summary = {"error": str(e)}
    return summary, clients, cases, days


@app.route("/api/summary")
def api_summary():
    if API_KEY and request.args.get("key", "") != API_KEY:
        return jsonify({"error": "unauthorized"}), 401
    summary, clients, cases, days = fetch_data()
    return jsonify({"summary": summary, "clients": clients, "cases": cases, "days": days})


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/")
def index():
    summary, clients, cases, days = fetch_data()
    return Response(render_page(summary, cases, days), mimetype="text/html")


def vnd(n):
    try:
        return "{:,.0f}".format(float(n or 0)).replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def esc(x):
    return (str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def build_chart(days):
    if not days:
        return '<div class="empty">Chưa có dữ liệu theo ngày.</div>'
    maxu = max((d.get("units", 0) or 0) for d in days) or 1
    n = len(days)
    bw, gap, ch, top, bot = 26, 12, 150, 24, 24
    W = gap + n * (bw + gap)
    H = top + ch + bot
    bars = ""
    for i, d in enumerate(days):
        u = d.get("units", 0) or 0
        h = max(3, round(u / maxu * ch))
        x = gap + i * (bw + gap)
        y = top + (ch - h)
        dd = str(d.get("day", ""))[-2:]
        bars += ('<rect class="bar" x="%d" y="%d" width="%d" height="%d" rx="6" fill="url(#g)" '
                 'style="--i:%d"/>' % (x, y, bw, h, i))
        bars += '<text class="cv" x="%d" y="%d" text-anchor="middle">%d</text>' % (x + bw // 2, y - 7, u)
        bars += '<text class="cd" x="%d" y="%d" text-anchor="middle">%s</text>' % (x + bw // 2, H - 7, esc(dd))
    return ('<div class="chartbox"><svg viewBox="0 0 %d %d" width="%d" height="%d">'
            '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="#d8b4fe"/><stop offset="1" stop-color="#7c3aed"/>'
            '</linearGradient></defs>%s</svg></div>' % (W, H, W, H, bars))


def render_page(s, cases, days):
    if s.get("error"):
        return _shell(
            '<div class="err">Lỗi đọc Turso: ' + esc(s["error"]) +
            '<br><small>Kiểm tra TURSO_URL / TURSO_TOKEN trên Render.</small></div>', "—")

    # Ngay "hom nay" = phan ngay cua updated_at (luc day len cloud)
    today = str(s.get("updated_at", "")).split(" ")[0]
    if not today and cases:
        today = str(cases[0].get("date", ""))

    # MODEL tinh theo CASE: hom nay co bao nhieu case can IN (model) vs KHONG
    today_cases = [c for c in cases if str(c.get("date", "")) == today]
    m_in = sum(1 for c in today_cases if c.get("model"))
    m_no = len(today_cases) - m_in

    cards = (
        '<section class="summary">'
        '<div class="card v"><span>Ca tháng</span><strong>' + str(s.get("total_cases", 0)) + '</strong></div>'
        '<div class="card b"><span>Đơn vị tháng</span><strong>' + str(s.get("total_units", 0)) + '</strong></div>'
        '<div class="card o hl"><span>Ca hôm nay</span><strong>' + str(s.get("today_cases", 0)) + '</strong></div>'
        '<div class="card o hl"><span>Đơn vị hôm nay</span><strong>' + str(s.get("today_units", 0)) + '</strong></div>'
        '<div class="card mcard"><span>Model hôm nay (theo case)</span>'
        '<div class="msplit"><div class="mseg in"><b>' + str(m_in) + '</b><i>cần in</i></div>'
        '<div class="mseg no"><b>' + str(m_no) + '</b><i>không in</i></div></div></div>'
        '</section>')

    chart = ('<section class="panel"><div class="panel-title"><h2>Sản lượng theo ngày</h2></div>'
             + build_chart(days) + '</section>')

    # Nhung data ca + ngay -> JS tu render (loc Hom nay/Tuan/Thang + tab khach)
    slim = [{"name": c.get("name", ""), "client": c.get("client", "") or "(khác)",
             "units": c.get("units", 0), "model": 1 if c.get("model") else 0,
             "date": c.get("date", "")} for c in cases]
    data_js = json.dumps({"today": today, "cases": slim}, ensure_ascii=False).replace("<", "\\u003c")

    panel = (
        '<section class="panel">'
        '<div class="panel-title"><h2>Danh sách ca</h2>'
        '<div class="periods">'
        '<button class="per active" data-p="today">Hôm nay</button>'
        '<button class="per" data-p="week">Tuần này</button>'
        '<button class="per" data-p="month">Tháng này</button>'
        '</div></div>'
        '<div class="tabs" id="tabs"></div>'
        '<div class="case-list" id="list"></div></section>'
        '<script>window.DATA=' + data_js + ';</script>')

    return _shell(cards + chart + panel, s.get("updated_at", "—"), s.get("month", ""))


def _shell(body, updated, month=""):
    return """<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#140c1f">
<title>PainLAB · Sản lượng</title>
<style>
:root{font-family:Inter,'Segoe UI',-apple-system,system-ui,sans-serif;
 --vio:#c4b5fd;--muted:#9d8fb8;--border:rgba(139,92,246,.22);--card:rgba(30,18,46,.62)}
*{box-sizing:border-box;margin:0}
body{min-height:100vh;color:#ece6f7;position:relative;overflow-x:hidden;
 background:#120a1e}
/* hinh hoc trang tri: cac khoi gradient mo */
body::before,body::after{content:"";position:fixed;border-radius:50%;filter:blur(70px);z-index:-2;pointer-events:none}
body::before{width:380px;height:380px;top:-120px;right:-90px;
 background:radial-gradient(circle,rgba(139,92,246,.42),transparent 70%)}
body::after{width:420px;height:420px;bottom:-160px;left:-120px;
 background:radial-gradient(circle,rgba(236,72,153,.20),transparent 70%)}
.mesh{position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.5;
 background:
  radial-gradient(circle at 80% 8%,rgba(124,58,237,.18),transparent 30%),
  radial-gradient(circle at 0% 60%,rgba(59,130,246,.12),transparent 28%);}
.grid{position:fixed;inset:0;z-index:-1;pointer-events:none;opacity:.06;
 background-image:linear-gradient(rgba(196,181,253,.6) 1px,transparent 1px),
  linear-gradient(90deg,rgba(196,181,253,.6) 1px,transparent 1px);
 background-size:34px 34px;mask-image:radial-gradient(circle at 50% 0%,#000,transparent 70%)}
h1,h2,h3,p{margin:0}
header{position:sticky;top:0;z-index:10;display:flex;align-items:center;justify-content:space-between;
 gap:14px;padding:max(18px,env(safe-area-inset-top)) 18px 16px;background:rgba(18,10,30,.72);
 border-bottom:1px solid var(--border);backdrop-filter:blur(22px) saturate(130%)}
.brand{display:flex;align-items:center;gap:12px}
.logo{width:38px;height:38px;flex:0 0 auto;border-radius:12px;display:grid;place-items:center;
 background:conic-gradient(from 140deg,#7c3aed,#c4b5fd,#ec4899,#7c3aed);
 box-shadow:0 6px 20px -6px rgba(139,92,246,.8);transform:rotate(8deg)}
.logo b{transform:rotate(-8deg);font-size:18px}
.eyebrow{color:var(--vio);font-size:11px;font-weight:800;letter-spacing:.2em;text-transform:uppercase}
h1{font-size:23px;line-height:1.05;letter-spacing:-.02em;
 background:linear-gradient(90deg,#fff,#c4b5fd);-webkit-background-clip:text;background-clip:text;color:transparent}
#status{color:var(--muted);font-size:12px;white-space:nowrap;text-align:right}
main{padding:18px 14px calc(30px + env(safe-area-inset-bottom));max-width:980px;margin:auto;position:relative}
.summary{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.card,.panel,.case-row{border:1px solid var(--border);border-radius:22px;background:var(--card);
 box-shadow:0 18px 44px rgba(10,5,20,.45);backdrop-filter:blur(16px) saturate(130%)}
.card{position:relative;overflow:hidden;min-height:116px;padding:18px;display:flex;flex-direction:column;justify-content:space-between}
.card::after{content:"";position:absolute;right:-22px;top:-22px;width:80px;height:80px;border-radius:50%;
 background:radial-gradient(circle,rgba(139,92,246,.30),transparent 70%)}
.card span{color:var(--muted);font-size:11px;letter-spacing:.06em;text-transform:uppercase;font-weight:700}
.card strong{font-size:40px;line-height:1;font-weight:900;color:var(--vio);
 text-shadow:0 0 22px rgba(139,92,246,.6)}
.card.b strong{color:#93c5fd;text-shadow:0 0 22px rgba(96,165,250,.55)}
.card.o strong{color:#fb923c;text-shadow:0 0 22px rgba(249,115,22,.55)}
.card.o::after{background:radial-gradient(circle,rgba(249,115,22,.30),transparent 70%)}
.card.hl{background:linear-gradient(180deg,rgba(60,28,30,.5),rgba(30,18,46,.62))}
.panel{margin-top:16px;padding:18px}
.mcard{border-color:rgba(249,115,22,.34)}
.mcard span{color:#fdba74}
.msplit{display:flex;gap:20px;align-items:flex-end}
.mseg b{font-size:38px;font-weight:900;line-height:1;display:block}
.mseg.in b{color:#fb923c;text-shadow:0 0 22px rgba(249,115,22,.55)}
.mseg.no b{color:#9d8fb8}
.mseg i{font-style:normal;display:block;margin-top:5px;font-size:10px;font-weight:700;
 letter-spacing:.04em;text-transform:uppercase;color:var(--muted)}
.panel-title{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;margin-bottom:14px}
h2{font-size:16px;color:#efe9fb;font-weight:800;letter-spacing:.01em}
.chartbox{overflow-x:auto;padding-bottom:4px}
.chartbox svg{display:block;max-width:100%}
.bar{transform:scaleY(0);transform-origin:bottom;transform-box:fill-box;
 animation:grow .6s cubic-bezier(.2,.85,.25,1) forwards;animation-delay:calc(var(--i)*.035s)}
@keyframes grow{to{transform:scaleY(1)}}
.cv{fill:#c4b5fd;font-size:11px;font-weight:800}
.cd{fill:#8b7caa;font-size:10px}
.daydate{color:var(--vio);font-size:13px;font-weight:700;background:rgba(139,92,246,.14);
 padding:5px 12px;border-radius:10px;border:1px solid var(--border)}
.periods{display:flex;gap:6px;background:rgba(15,8,26,.6);border:1px solid var(--border);
 border-radius:13px;padding:4px}
.per{cursor:pointer;padding:8px 14px;border-radius:10px;font-size:13px;font-weight:700;font-family:inherit;
 color:#cdbdf0;background:transparent;border:none;white-space:nowrap;transition:.14s}
.per.active{color:#fff;background:linear-gradient(135deg,#7c3aed,#9333ea);
 box-shadow:0 6px 16px -8px rgba(139,92,246,.9)}
.tabs{display:flex;gap:8px;overflow-x:auto;padding-bottom:12px;margin-bottom:4px;scrollbar-width:thin}
.tabs::-webkit-scrollbar{height:5px}.tabs::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}
.tab{flex:0 0 auto;cursor:pointer;padding:9px 15px;border-radius:13px;font-size:14px;font-weight:700;
 color:#cdbdf0;background:rgba(30,18,46,.7);border:1px solid var(--border);white-space:nowrap;
 display:flex;align-items:center;gap:7px;transition:.14s;font-family:inherit}
.tab i{font-style:normal;font-size:11px;font-weight:800;padding:1px 7px;border-radius:8px;
 background:rgba(139,92,246,.2);color:#ddd0ff}
.tab:hover{border-color:rgba(139,92,246,.5)}
.tab.active{color:#fff;background:linear-gradient(135deg,#7c3aed,#9333ea);border-color:transparent;
 box-shadow:0 6px 18px -8px rgba(139,92,246,.9)}
.tab.active i{background:rgba(255,255,255,.25);color:#fff}
.case-list{display:grid;gap:11px}
.case-row{padding:15px 16px;transition:transform .14s,border-color .14s,background .14s}
.case-row:hover{border-color:rgba(139,92,246,.55);background:rgba(45,28,66,.72);transform:translateY(-2px)}
.row-top{display:flex;align-items:center;justify-content:space-between;gap:10px}
.case-row h3{margin-top:9px;font-size:18px;color:#f3eeff;word-break:break-word}
.case-meta{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px}
.date{color:var(--muted);font-size:12px;font-weight:600;white-space:nowrap}
.pill{padding:5px 11px;border-radius:10px;font-size:12px;font-weight:700;white-space:nowrap}
.pill.cli{color:#ddd0ff;background:rgba(139,92,246,.18);border:1px solid rgba(139,92,246,.4)}
.pill.u{color:#bae6fd;background:rgba(56,189,248,.16);border:1px solid rgba(56,189,248,.36)}
.pill.model{color:#fed7aa;background:rgba(249,115,22,.18);border:1px solid rgba(249,115,22,.42)}
.empty{color:var(--muted);padding:18px 4px;font-size:14px;line-height:1.6}
.err{margin:18px;padding:18px;color:#fda4af;background:rgba(80,20,40,.4);border:1px solid rgba(244,63,94,.4);border-radius:18px}
@media(min-width:700px){.summary{grid-template-columns:repeat(4,1fr)}}
</style></head><body>
<div class="mesh"></div><div class="grid"></div>
<header><div class="brand"><span class="logo"><b>🦷</b></span>
<div><p class="eyebrow">PainLAB</p><h1>Tổng quan sản lượng</h1></div></div>
<span id="status">⟳ """ + esc(updated) + ("" if not month else " · " + esc(month)) + """</span></header>
<main>""" + body + """</main>
<script>
// Loc Hom nay / Tuan / Thang + tab khach — tat ca client-side, KHONG reload
(function(){
  const D=window.DATA||{today:"",cases:[]};
  const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  // m. Thu 2 dau tuan chua "today"
  let monday="";
  if(D.today){const d=new Date(D.today+"T00:00:00Z");const wd=(d.getUTCDay()+6)%7;
    d.setUTCDate(d.getUTCDate()-wd);monday=d.toISOString().slice(0,10);}
  const state={period:'today',client:'__all__'};
  function inPeriod(date){
    if(state.period==='month')return true;
    if(state.period==='today')return date===D.today;
    return monday?date>=monday&&date<=D.today:date===D.today; // week
  }
  function render(){
    const inP=D.cases.filter(c=>inPeriod(c.date));
    // tab khach tu danh sach trong moc dang chon
    const counts={};inP.forEach(c=>{counts[c.client]=(counts[c.client]||0)+1;});
    const clis=Object.keys(counts).sort((a,b)=>counts[b]-counts[a]);
    if(!(state.client in counts)&&state.client!=='__all__')state.client='__all__';
    let th='<button class="tab'+(state.client==='__all__'?' active':'')+'" data-t="__all__">Tất cả <i>'+inP.length+'</i></button>';
    clis.forEach(cc=>{th+='<button class="tab'+(state.client===cc?' active':'')+'" data-t="'+esc(cc)+'">'+esc(cc)+' <i>'+counts[cc]+'</i></button>';});
    document.getElementById('tabs').innerHTML=th;
    // danh sach
    const show=inP.filter(c=>state.client==='__all__'||c.client===state.client);
    let h='';
    show.forEach(c=>{
      const model=c.model?'<div class="case-meta"><span class="pill model">MODEL</span></div>':'';
      h+='<div class="case-row"><div class="row-top"><span class="pill cli">'+esc(c.client)+
        '</span><span class="pill u">'+c.units+' đv · '+c.date.slice(5)+'</span></div>'+
        '<h3>'+esc(c.name)+'</h3>'+model+'</div>';
    });
    document.getElementById('list').innerHTML=h||'<div class="empty">Không có ca nào trong mốc này.</div>';
  }
  document.querySelectorAll('.per').forEach(b=>b.addEventListener('click',()=>{
    document.querySelectorAll('.per').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');state.period=b.dataset.p;state.client='__all__';render();}));
  document.getElementById('tabs').addEventListener('click',e=>{
    const b=e.target.closest('.tab');if(!b)return;state.client=b.dataset.t;render();});
  render();
})();
</script>
</body></html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
