# -*- coding: utf-8 -*-
"""雲端 / 正式啟動:讀環境變數 PORT(Render 等平台會自動給)"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("LAYERS_DIR", os.path.join(HERE, "..", "layers", "current"))
sys.path.insert(0, HERE)
import app
from waitress import serve
port = int(os.environ.get("PORT", 5000))
print(f" * 控制點查詢系統 啟動於 port {port}")
serve(app.app, host="0.0.0.0", port=port, threads=8)
