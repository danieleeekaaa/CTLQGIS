# -*- coding: utf-8 -*-
"""
CTL-Project 控制點查詢網站
===========================
QGIS 在 layers/current/ 編輯存檔 → 伺服器自動重載 → 網頁即時更新

啟動: python app.py   (正式多人: python serve.py)
"""
import glob, math, os, re, threading, time
from flask import Flask, jsonify, send_from_directory

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
LAYERS_DIR = os.environ.get("LAYERS_DIR", os.path.join(BASE_DIR, "..", "layers", "current"))
PHOTO_ROOT = os.environ.get("PHOTO_ROOT", "Y:/PHOTO")
POLL_SEC   = int(os.environ.get("POLL_SEC", "3600"))  # 雲端資料靜態,一小時檢查一次即可

app = Flask(__name__)

# ── 圖層設定:檔名前綴 → 顯示名稱 / 座標系 ──────────────────
# 檔名用英文,顯示名稱用中文
LAYER_CONFIG = {
    "ctl67_main":   {"label": "67圖根(全)",   "epsg": 3828, "priority": 1},
    "ctl67_supp":   {"label": "67補點",        "epsg": 3828, "priority": 2},
    "ctl67_urban":  {"label": "都發局67圖根",  "epsg": 3828, "priority": 5},
    "ctl97_main":   {"label": "97圖根",        "epsg": 3826, "priority": 3},
    "ctl97_anding": {"label": "安定區97",      "epsg": 3826, "priority": 4},
}

# ── 座標轉換 ─────────────────────────────────────────────────
try:
    from pyproj import Transformer
    _TR = {
        3828: Transformer.from_crs("EPSG:3828", "EPSG:4326", always_xy=True),
        3826: Transformer.from_crs("EPSG:3826", "EPSG:4326", always_xy=True),
    }
    def to_wgs84(x, y, epsg=3828):
        lng, lat = _TR[epsg].transform(x, y)
        return round(lat, 8), round(lng, 8)
    ENGINE = "pyproj"
except Exception:
    def _tm2_to_wgs(x, y, epsg):
        if epsg == 3828:
            a, rf = 6378160.0, 298.25
            dx, dy, dz = -752.0, -358.0, -179.0
        else:
            a, rf = 6378137.0, 298.257222101
            dx = dy = dz = 0.0
        f = 1/rf; e2 = f*(2-f); k0 = 0.9999; lon0 = math.radians(121); fe = 250000
        e1 = (1-math.sqrt(1-e2))/(1+math.sqrt(1-e2))
        M = y/k0; mu = M/(a*(1-e2/4-3*e2**2/64-5*e2**3/256))
        phi1 = mu + (3*e1/2-27*e1**3/32)*math.sin(2*mu) + \
               (21*e1**2/16-55*e1**4/32)*math.sin(4*mu) + \
               (151*e1**3/96)*math.sin(6*mu)
        ep2 = e2/(1-e2); s=math.sin(phi1); c=math.cos(phi1); t=math.tan(phi1)
        C1=ep2*c*c; T1=t*t; N1=a/math.sqrt(1-e2*s*s); R1=a*(1-e2)/(1-e2*s*s)**1.5
        D = (x-fe)/(N1*k0)
        phi = phi1-(N1*t/R1)*(D*D/2-(5+3*T1+10*C1-4*C1*C1-9*ep2)*D**4/24)
        lam = lon0+(D-(1+2*T1+C1)*D**3/6)/c
        N=a/math.sqrt(1-e2*math.sin(phi)**2)
        X=N*math.cos(phi)*math.cos(lam)+dx; Y2=N*math.cos(phi)*math.sin(lam)+dy
        Z=(N*(1-e2))*math.sin(phi)+dz
        a2=6378137.0; e2b=1/298.257223563*(2-1/298.257223563)
        p=math.hypot(X,Y2); phi2=math.atan2(Z,p*(1-e2b))
        for _ in range(5):
            N2=a2/math.sqrt(1-e2b*math.sin(phi2)**2)
            phi2=math.atan2(Z+e2b*N2*math.sin(phi2),p)
        return round(math.degrees(phi2),8), round(math.degrees(math.atan2(Y2,X)),8)
    def to_wgs84(x, y, epsg=3828):
        return _tm2_to_wgs(x, y, epsg)
    ENGINE = "內建TM2反算"


# ── 圖層讀取 ─────────────────────────────────────────────────
def _img(raw):
    if not raw: return None
    p = str(raw).replace("\\", "/")
    m = re.search(r"PHOTO/(.+)$", p, flags=re.I)
    return "/photos/" + (m.group(1) if m else os.path.basename(p))

def read_layer(shp_path, cfg, layer_key):
    import shapefile
    sf = shapefile.Reader(shp_path, encoding='utf-8')
    epsg = cfg["epsg"]
    coord_x = "X_67" if epsg == 3828 else "X_97"
    coord_y = "Y_67" if epsg == 3828 else "Y_97"
    out = []
    for i, sr in enumerate(sf.iterShapeRecords()):
        r = sr.record.as_dict()
        if sr.shape.points:
            sx, sy = sr.shape.points[0]
        elif r.get(coord_x) and r.get(coord_y):
            sx, sy = float(r[coord_x]), float(r[coord_y])
        else:
            continue
        lat, lng = to_wgs84(sx, sy, epsg)
        if not (22.5 < lat < 25.5 and 119.0 < lng < 122.5):
            continue
        d = {
            "id":        f"{layer_key}_{i}",
            "系統":      "TWD67" if epsg == 3828 else "TWD97",
            "圖層":      cfg["label"],
            "priority":  cfg["priority"],
            "NO":        r.get("NO") or "",
            "TYPE":      r.get("TYPE") or "",
            "DATE":      r.get("DATE") or "",
            "X":         round(sx, 3),
            "Y":         round(sy, 3),
            "PS":        r.get("PS") or "",
            "TRANS_TYPE":r.get("TRANS_TYPE") or "",
            "lat":       lat,
            "lng":       lng,
            "imgs":      [u for u in (_img(r.get(f"PHOTO{j}")) for j in range(1,6)) if u],
        }
        out.append(d)
    return out


def resolve_layers():
    result = []
    layers_dir = os.environ.get("LAYERS_DIR", LAYERS_DIR)
    for shp in sorted(glob.glob(os.path.join(layers_dir, "*.shp"))):
        stem = os.path.splitext(os.path.basename(shp))[0]
        cfg = None; key = None
        for prefix, c in LAYER_CONFIG.items():
            if stem.startswith(prefix):
                cfg = c; key = prefix; break
        if cfg is None:
            cfg = {"label": stem, "epsg": 3828, "priority": 99}
            key = stem
        result.append((shp, cfg, key))
    return result


def source_stamp():
    paths = [p for p,*_ in resolve_layers()]
    stamps = []
    for p in paths:
        stamps.append(os.path.getmtime(p))
        dbf = p[:-4]+".dbf"
        if os.path.exists(dbf): stamps.append(os.path.getmtime(dbf))
    return max(stamps) if stamps else 0


# ── 快取 ─────────────────────────────────────────────────────
CACHE = {"pts": [], "stamp": 0, "ts": None, "err": None, "stats": {}}
_lock = threading.Lock()

def reload(force=False):
    s = source_stamp()
    if not force and s == CACHE["stamp"]: return False
    all_pts, stats = [], {}
    try:
        layers = resolve_layers()
        if not layers:
            ld = os.environ.get("LAYERS_DIR", LAYERS_DIR)
            print(f" ! 警告:在 {os.path.abspath(ld)} 找不到任何 .shp 圖層檔")
        for shp, cfg, key in layers:
            rows = read_layer(shp, cfg, key)
            stats[cfg["label"]] = len(rows)
            all_pts.extend(rows)
        with _lock:
            CACHE.update(pts=all_pts, stamp=s,
                         ts=time.strftime("%Y-%m-%d %H:%M:%S"),
                         stats=stats, err=None)
        total = len(all_pts)
        if total:
            print(f" * 載入 {total} 點 | " + " | ".join(f"{k}:{v}" for k,v in stats.items()))
        return True
    except Exception as e:
        import traceback; traceback.print_exc()
        with _lock: CACHE["err"] = str(e)
        return False

def _watcher():
    while True:
        time.sleep(POLL_SEC)
        try: reload()
        except Exception as e: print("監看錯誤:", e)

reload(force=True)
threading.Thread(target=_watcher, daemon=True).start()


# ── 路由 ─────────────────────────────────────────────────────
TPL = os.path.join(BASE_DIR, "web", "templates") if os.path.isdir(os.path.join(BASE_DIR, "web", "templates")) else os.path.join(BASE_DIR, "templates")

@app.route("/")
def index(): return send_from_directory(TPL, "index.html")

@app.route("/photos/<path:rel>")
def photos(rel):
    root = os.environ.get("PHOTO_ROOT", PHOTO_ROOT)
    return send_from_directory(root, rel)

@app.route("/api/points")
def api_points():
    with _lock: return jsonify(CACHE["pts"])

@app.route("/api/meta")
def api_meta():
    with _lock:
        return jsonify(stamp=CACHE["stamp"], ts=CACHE["ts"],
                       total=len(CACHE["pts"]), stats=CACHE["stats"],
                       engine=ENGINE, err=CACHE["err"])

if __name__ == "__main__":
    ld = os.path.abspath(os.environ.get("LAYERS_DIR", LAYERS_DIR))
    print(f" * 圖層目錄: {ld}")
    print(f" * 前台: http://127.0.0.1:5000")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
