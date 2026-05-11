"""
安全庫存自動化系統 - 啟動器
Safety Stock Automation - Launcher

Version: 4.2.2 Bilingual
Author: 松鼠
Last Updated: 2026-01-16

用法 / Usage:
    python launcher.py              # 預設繁體中文 / Default: Traditional Chinese
    python launcher.py --lang en    # English
    python launcher.py --lang zh    # 繁體中文
"""

import sys
import os
import webbrowser
import threading
import time
import argparse
from pathlib import Path


# ===========================================================================
# 語言字串 / Language strings
# ===========================================================================

_STRINGS = {
    'zh': {
        # 標題橫幅 / Banner
        'banner': """
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║     🧮  安全庫存自動化系統 v4.2.2                       ║
║         Safety Stock Automation System                   ║
║                                                          ║
║         架構: Python (Flask) + HTML UI                   ║
║         模式: 混合式 Web 應用                            ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""",
        # 依賴套件檢查 / Dependency check
        'checking_deps':   '🔍 檢查依賴套件...',
        'dep_ok':          '  ✅ {name}',
        'dep_missing':     '  ❌ {name} (缺失)',
        'deps_missing':    '\n❌ 缺少依賴套件:\n   {names}',
        'deps_install':    '\n請執行: pip install flask pandas openpyxl xlsxwriter pyyaml',
        'deps_all_ok':     '✅ 所有依賴已安裝\n',

        # 專案結構檢查 / Project structure check
        'checking_struct': '🔍 檢查專案結構...',
        'dir_created':     '  ⚠️  創建目錄: {dir}',
        'dir_ok':          '  ✅ {dir}/',
        'file_missing':    '  ❌ 缺少檔案: {file}',
        'app_missing':     '\n❌ 錯誤: 找不到 app.py\n   請確保在正確的目錄下執行',
        'file_ok':         '  ✅ {file}',
        'struct_ok':       '✅ 專案結構完整\n',

        # 啟動資訊 / Startup info
        'starting':        '🚀 正在啟動系統...',
        'features_title':  '📋 功能特色:',
        'features': [
            '  • 檔案上傳與資料載入',
            '  • 分倉 vs 總倉對比分析',
            '  • 移動平均平滑計算',
            '  • 季度趨勢可視化',
            '  • Excel / JSON 匯出',
        ],
        'server_addr':     '🌐 服務位址: http://localhost:5000',
        'stop_hint':       '💡 關閉此視窗即可停止系統',

        # 瀏覽器 / Browser
        'opening_browser': '🌐 正在開啟瀏覽器: {url}',

        # 結束 / Exit
        'stopped':         '\n\n🛑 系統已停止',
        'thank_you':       '感謝使用！',
        'error':           '\n\n❌ 錯誤: {error}',
    },

    'en': {
        # Banner
        'banner': """
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║     🧮  Safety Stock Automation System v4.2.2           ║
║         安全庫存自動化系統                               ║
║                                                          ║
║         Stack : Python (Flask) + HTML UI                 ║
║         Mode  : Hybrid Web Application                   ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""",
        # Dependency check
        'checking_deps':   '🔍 Checking dependencies...',
        'dep_ok':          '  ✅ {name}',
        'dep_missing':     '  ❌ {name} (missing)',
        'deps_missing':    '\n❌ Missing packages:\n   {names}',
        'deps_install':    '\nRun: pip install flask pandas openpyxl xlsxwriter pyyaml',
        'deps_all_ok':     '✅ All dependencies installed\n',

        # Project structure check
        'checking_struct': '🔍 Checking project structure...',
        'dir_created':     '  ⚠️  Created directory: {dir}',
        'dir_ok':          '  ✅ {dir}/',
        'file_missing':    '  ❌ Missing file: {file}',
        'app_missing':     '\n❌ Error: app.py not found\n   Please run from the correct directory',
        'file_ok':         '  ✅ {file}',
        'struct_ok':       '✅ Project structure OK\n',

        # Startup info
        'starting':        '🚀 Starting system...',
        'features_title':  '📋 Features:',
        'features': [
            '  • File upload & data loading',
            '  • By-warehouse vs consolidated comparison',
            '  • Moving average smoothing',
            '  • Quarterly trend visualization',
            '  • Excel / JSON export',
        ],
        'server_addr':     '🌐 Server address: http://localhost:5000',
        'stop_hint':       '💡 Close this window to stop the system',

        # Browser
        'opening_browser': '🌐 Opening browser: {url}',

        # Exit
        'stopped':         '\n\n🛑 System stopped',
        'thank_you':       'Thank you for using the system!',
        'error':           '\n\n❌ Error: {error}',
    },
}


def _t(key: str, **kwargs) -> str:
    """Return the translated string for the current language."""
    s = _STRINGS[_LANG].get(key, _STRINGS['zh'].get(key, key))
    return s.format(**kwargs) if kwargs else s


# ===========================================================================
# 語言初始化 / Language initialisation
# (must happen before any _t() call)
# ===========================================================================

def _parse_lang() -> str:
    """
    Determine language from --lang CLI argument.
    Falls back to 'zh' if not specified or invalid.
    Handles --lang before argparse so the rest of the app can use _t() early.
    """
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == '--lang' and i < len(sys.argv):
            lang = sys.argv[i + 1].lower().strip()
            if lang in ('en', 'english'):
                return 'en'
            if lang in ('zh', 'chinese', 'zh-tw'):
                return 'zh'
    return 'zh'


_LANG: str = _parse_lang()


# ===========================================================================
# 核心功能 / Core functions
# ===========================================================================

def check_dependencies() -> None:
    """檢查必要的依賴套件 / Check required packages."""
    print(_t('checking_deps'))

    missing = []
    required = {
        'flask':      'Flask',
        'pandas':     'Pandas',
        'openpyxl':   'OpenPyXL',
        'xlsxwriter': 'XlsxWriter',
        'yaml':       'PyYAML',
    }

    for module, name in required.items():
        try:
            __import__(module)
            print(_t('dep_ok', name=name))
        except ImportError:
            missing.append(name)
            print(_t('dep_missing', name=name))

    if missing:
        print(_t('deps_missing', names=', '.join(missing)))
        print(_t('deps_install'))
        sys.exit(1)

    print(_t('deps_all_ok'))


def check_project_structure() -> None:
    """檢查專案結構 / Check project structure."""
    print(_t('checking_struct'))

    required_dirs  = ['src', 'config', 'templates', 'static', 'uploads']
    required_files = ['app.py', 'config/config.yaml']

    for directory in required_dirs:
        path = Path(directory)
        if not path.exists():
            print(_t('dir_created', dir=directory))
            path.mkdir(parents=True, exist_ok=True)
        else:
            print(_t('dir_ok', dir=directory))

    for file in required_files:
        path = Path(file)
        if not path.exists():
            print(_t('file_missing', file=file))
            if file == 'app.py':
                print(_t('app_missing'))
                sys.exit(1)
        else:
            print(_t('file_ok', file=file))

    print(_t('struct_ok'))


def start_flask_app() -> None:
    """啟動 Flask 應用 / Start the Flask application."""
    os.environ['FLASK_ENV'] = 'production'

    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)  # silence startup noise

    from app import app
    app.run(
        host='127.0.0.1',
        port=5000,
        debug=False,
        use_reloader=False,  # 避免重複啟動 / Prevent double-start
    )


def open_browser() -> None:
    """延遲後自動打開瀏覽器 / Open browser after Flask is ready."""
    time.sleep(1.5)
    url = 'http://localhost:5000'
    print(_t('opening_browser', url=url))
    webbrowser.open(url)


def print_banner() -> None:
    """顯示啟動橫幅 / Print startup banner."""
    print(_t('banner'))


# ===========================================================================
# 主程式 / Main entry point
# ===========================================================================

def main() -> None:
    print_banner()
    check_dependencies()
    check_project_structure()

    print('=' * 60)
    print(_t('starting'))
    print('=' * 60)
    print()
    print(_t('features_title'))
    for line in _t('features'):
        print(line)
    print()
    print(_t('server_addr'))
    print(_t('stop_hint'))
    print()
    print('=' * 60)
    print()

    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()

    try:
        start_flask_app()
    except KeyboardInterrupt:
        print(_t('stopped'))
        print(_t('thank_you'))
    except Exception as exc:
        print(_t('error', error=exc))
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
