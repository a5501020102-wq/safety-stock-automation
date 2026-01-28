"""
安全庫存自動化系統 - 啟動器
Safety Stock Automation - Launcher

Version: 4.2.1 Flask Hybrid
Author: 松鼠
Last Updated: 2025-01-14

一鍵啟動 Flask Web 應用
"""

import sys
import os
import webbrowser
import threading
import time
from pathlib import Path


def check_dependencies():
    """檢查必要的依賴套件"""
    print("🔍 檢查依賴套件...")

    missing = []
    required = {
        'flask': 'Flask',
        'pandas': 'Pandas',
        'openpyxl': 'OpenPyXL',
        'xlsxwriter': 'XlsxWriter',
        'yaml': 'PyYAML',
    }

    for module, name in required.items():
        try:
            __import__(module)
            print(f"  ✅ {name}")
        except ImportError:
            missing.append(name)
            print(f"  ❌ {name} (缺失)")

    if missing:
        print("\n❌ 缺少依賴套件:")
        print("   " + ", ".join(missing))
        print("\n請執行: pip install flask pandas openpyxl xlsxwriter pyyaml")
        sys.exit(1)

    print("✅ 所有依賴已安裝\n")


def check_project_structure():
    """檢查專案結構"""
    print("🔍 檢查專案結構...")

    required_dirs = ['src', 'config', 'templates', 'static', 'uploads']
    required_files = ['app.py', 'config/config.yaml']

    for directory in required_dirs:
        path = Path(directory)
        if not path.exists():
            print(f"  ⚠️  創建目錄: {directory}")
            path.mkdir(parents=True, exist_ok=True)
        else:
            print(f"  ✅ {directory}/")

    for file in required_files:
        path = Path(file)
        if not path.exists():
            print(f"  ❌ 缺少檔案: {file}")
            if file == 'app.py':
                print("\n❌ 錯誤: 找不到 app.py")
                print("   請確保在正確的目錄下執行")
                sys.exit(1)
        else:
            print(f"  ✅ {file}")

    print("✅ 專案結構完整\n")


def start_flask_app():
    """啟動 Flask 應用"""
    # 設定環境變數
    os.environ['FLASK_ENV'] = 'production'

    # 靜默 Flask 的啟動訊息
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    # 導入並啟動 Flask app
    from app import app
    app.run(
        host='127.0.0.1',
        port=5000,
        debug=False,
        use_reloader=False  # 避免重複啟動
    )


def open_browser():
    """延遲後自動打開瀏覽器"""
    time.sleep(1.5)  # 等待 Flask 啟動
    url = 'http://localhost:5000'
    print(f"🌐 正在開啟瀏覽器: {url}")
    webbrowser.open(url)


def print_banner():
    """顯示啟動橫幅"""
    banner = """
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║     🧮  安全庫存自動化系統 v4.2.1                       ║
║         Safety Stock Automation System                   ║
║                                                          ║
║         架構: Python (Flask) + HTML UI                   ║
║         模式: 混合式 Web 應用                            ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
"""
    print(banner)


def main():
    """主程式入口"""
    print_banner()

    # 檢查環境
    check_dependencies()
    check_project_structure()

    print("=" * 60)
    print("🚀 正在啟動系統...")
    print("=" * 60)
    print()
    print("📋 功能特色:")
    print("  • 檔案上傳與資料載入")
    print("  • 分倉 vs 總倉對比分析")
    print("  • 移動平均平滑計算")
    print("  • 季度趨勢可視化")
    print("  • Excel / JSON 匯出")
    print()
    print("🌐 服務位址: http://localhost:5000")
    print("💡 關閉此視窗即可停止系統")
    print()
    print("=" * 60)
    print()

    # 在背景線程中打開瀏覽器
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()

    # 啟動 Flask（這會阻塞主線程）
    try:
        start_flask_app()
    except KeyboardInterrupt:
        print("\n\n🛑 系統已停止")
        print("感謝使用！")
    except Exception as e:
        print(f"\n\n❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()