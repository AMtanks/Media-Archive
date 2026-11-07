"""Windows desktop launcher. The local server is also available for development."""
import argparse
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from app.server import create_app

FROZEN = getattr(sys, "frozen", False)
# Frozen: keep data next to the exe (portable); ffmpeg.exe placed beside it is picked up automatically.
ROOT = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent
RESOURCE_ROOT = Path(getattr(sys, '_MEIPASS', ROOT))
if FROZEN:
    os.environ["PATH"] = str(ROOT) + os.pathsep + os.environ.get("PATH", "")


def activate_running(port):
    import urllib.request
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{port}/activate", method="POST", headers={"X-Activate": "1"})
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status == 204
    except Exception:
        return False


def main():
    if "--worker" in sys.argv:
        from app.worker import main as worker_main
        return worker_main()
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="store_true", help="Open UI in default browser instead of desktop window")
    parser.add_argument("--headless", action="store_true", help="Run local server without opening a window")
    parser.add_argument("--port", type=int, default=17864)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--no-scheduler", action="store_true", help="For local UI verification")
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    from app import ffmpeg_fetch
    ffmpeg_fetch.add_to_path(args.data_dir)
    logging.basicConfig(filename=args.data_dir / "desktop.log", level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    # OS holds this lock even when the process crashes. Never start two schedulers on one database.
    if os.name == "nt":
        import ctypes
        import hashlib
        name = "Local\\XArchive-" + hashlib.sha256(str(args.data_dir.resolve()).lower().encode()).hexdigest()[:20]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.restype = ctypes.c_void_p
        mutex = kernel.CreateMutexW(None, False, name)
        if ctypes.get_last_error() == 183:
            # Already running (usually hidden in the tray): bring that window forward instead of opening a browser.
            if activate_running(args.port):
                return
            # The previous instance is still shutting down. Wait for it to let go of the lock, then start normally.
            kernel.CloseHandle(ctypes.c_void_p(mutex))
            for _ in range(150):
                time.sleep(.2)
                mutex = kernel.CreateMutexW(None, False, name)
                if ctypes.get_last_error() != 183:
                    break
                kernel.CloseHandle(ctypes.c_void_p(mutex))
                if activate_running(args.port):
                    return
            else:
                return
            # Its socket may linger briefly after exit.
            for _ in range(50):
                probe = socket.socket()
                try:
                    probe.bind(("127.0.0.1", args.port))
                    break
                except OSError:
                    time.sleep(.2)
                finally:
                    probe.close()
    app = create_app(args.data_dir, not args.no_scheduler)
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", args.port))
    except OSError:
        raise RuntimeError(f"本地端口 {args.port} 已被占用，请使用 --port 选择其他端口")
    sock.listen(128)
    url = f"http://127.0.0.1:{sock.getsockname()[1]}"
    config = uvicorn.Config(app, access_log=False, log_level="warning", log_config=None)
    server = uvicorn.Server(config)
    if args.headless:
        if sys.stdout:
            print(url, flush=True)
        server.run(sockets=[sock])
        return
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(.05)
    if args.browser:
        import webbrowser
        webbrowser.open(url)
        try:
            while thread.is_alive():
                thread.join(1)
        except KeyboardInterrupt:
            server.should_exit = True
        return
    import webview
    import pystray
    from PIL import Image
    window = webview.create_window("Media Archive", url, width=1360, height=900,
                                   min_size=(850, 620), background_color="#101419")
    quitting = threading.Event()
    login_lock = threading.Lock()
    login_window = None
    login_platform = None
    login_confirmed = threading.Event()

    def ui_text(zh, en):
        return en if app.state.store.get_setting('ui_language', 'zh-CN') == 'en' else zh

    def show(*_):
        window.show()
        window.restore()

    def quit_app(icon=None, item=None):
        quitting.set()
        app.state.engine.close()
        server.should_exit = True
        if login_window:
            login_window.destroy()
        tray.stop()
        window.destroy()

    def on_closing():
        if not quitting.is_set():
            window.hide()
            return False

    window.events.closing += on_closing

    def login(platform="twitter"):
        nonlocal login_window, login_platform
        from app.secrets import PlatformVault
        options = {
            "twitter": ("X", "https://x.com/i/flow/login", {"x.com", "twitter.com"}, {"auth_token", "ct0"}, "auth_token"),
            "instagram": ("Instagram", "https://www.instagram.com/accounts/login/", {"instagram.com"}, {"sessionid", "csrftoken", "ds_user_id", "mid", "ig_did", "datr"}, "sessionid"),
            "weibo": ("微博 / Weibo", "https://weibo.com/login.php", {"weibo.com"}, {"SUB", "SUBP", "XSRF-TOKEN"}, "SUB"),
        }
        if platform not in options:
            raise ValueError("不支持的平台")
        label, login_url, domains, names, required = options[platform]
        if not login_lock.acquire(blocking=False):
            if login_window:
                login_window.show()
            return
        try:
            login_platform = platform
            login_confirmed.clear()
            en_label = 'Weibo' if platform == 'weibo' else label
            login_window = webview.create_window(ui_text(f"登录 {label} · 成功后自动保存", f"Sign in to {en_label} · saved after login"), login_url,
                                                 width=650, height=820, min_size=(500, 600))
            alive = threading.Event()
            alive.set()
            login_window.events.closed += lambda: alive.clear()

            def monitor():
                try:
                    while alive.is_set() and not quitting.is_set():
                        time.sleep(2)
                        try:
                            cookies = login_window.get_cookies()
                            values = {}
                            for cookie in cookies:
                                for key, morsel in cookie.items():
                                    if key in names and morsel["domain"].lstrip(".") in domains:
                                        values[key] = morsel.value
                            if values.get(required) and (platform != "weibo" or login_confirmed.is_set()):
                                if platform == "twitter":
                                    app.state.vault.save(values["auth_token"], values.get("ct0", ""))
                                else:
                                    PlatformVault(app.state.store.root, platform).save(values)
                                app.state.store.add_event(None, "success", f"{label} 登录凭证已加密保存")
                                login_window.destroy()
                                show()
                                return
                        except Exception:
                            pass
                finally:
                    login_lock.release()
            threading.Thread(target=monitor, daemon=True).start()
        except Exception:
            login_lock.release()
            raise

    def finish_weibo_login():
        if not login_lock.locked() or login_platform != 'weibo':
            return False
        login_confirmed.set()
        return True

    def pick_folder():
        result = window.create_file_dialog(webview.FileDialog.FOLDER)
        return str(result[0]) if result else ""

    app.state.login_callback = login
    app.state.finish_weibo_login = finish_weibo_login
    app.state.folder_callback = pick_folder
    app.state.activate_callback = lambda: False if quitting.is_set() else show()
    with Image.open(RESOURCE_ROOT / 'assets' / 'app-icon.png') as icon_image:
        image = icon_image.convert('RGBA').resize((64, 64), Image.Resampling.LANCZOS)
    tray = pystray.Icon("MediaArchive", image, "Media Archive", menu=pystray.Menu(
        pystray.MenuItem(lambda _: ui_text("打开 Media Archive", "Open Media Archive"), show, default=True),
        pystray.MenuItem(lambda _: ui_text("打开下载文件夹", "Open download folder"), lambda *_: os.startfile(app.state.store.get_setting("download_dir"))
                         if Path(app.state.store.get_setting("download_dir")).exists() else None),
        pystray.MenuItem(lambda _: ui_text("退出并停止同步", "Quit and stop syncing"), quit_app),
    ))
    app.state.language_callback = lambda: tray.update_menu()
    tray.run_detached()
    try:
        webview.start(gui="edgechromium", debug=False, private_mode=False,
                      icon=str(RESOURCE_ROOT / 'assets' / 'app-icon.ico'),
                      storage_path=str(args.data_dir / "webview"))
    finally:
        quitting.set()
        tray.stop()
        server.should_exit = True
        app.state.engine.close()
        thread.join(timeout=5)
        sock.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        import traceback
        text = traceback.format_exc()
        (ROOT / "startup-error.log").write_text(text, encoding="utf-8")
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "启动失败 / Startup failed.\nPlease see startup-error.log.", "Media Archive", 16)
        raise
