"""
Safety Stock Automation - Flask API 進入點 (v5.1.0, Stateless)

Render 以 `gunicorn app:app` 啟動；本機可直接 `python app.py`。
路由、參數驗證與業務流程分別在 src/api/ 與 src/services/。

Endpoints:
    GET  /                           API health check
    GET  /health                     Liveness probe
    GET  /api/material-groups        Material master categories
    GET  /legacy                     Legacy Jinja UI
    POST /api/upload/<file_type>     Upload sales/price/plan file
    POST /api/calculate              Run safety stock calculation
    POST /api/export/excel           Generate Excel export
    POST /api/export/sap             Generate SAP MM17 export
    POST /api/ma-detail              Compute moving average detail (pure function)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log", encoding="utf-8"),
    ],
)

# 讓 `from src...` 在任何工作目錄下都能 import
sys.path.insert(0, str(Path(__file__).parent))

from src.api.app_factory import create_app  # noqa: E402 - 需在 sys.path 設定之後

DEFAULT_PORT = 5000

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    app.run(host="0.0.0.0", port=port, debug=app.config["DEBUG_ERRORS"])
