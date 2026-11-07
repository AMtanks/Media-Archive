"""yt-dlp ships frozen inside the exe. When a stream download fails, look for a newer release once and
use it from the data folder on the next run. Never raises."""
import importlib.abc
import importlib.machinery
import importlib.util
import io
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

PYPI = "https://pypi.org/pypi/yt-dlp/json"


def _dir(data_dir):
    return Path(data_dir) / "ytdlp"


class _LocalFinder(importlib.abc.MetaPathFinder):
    def __init__(self, folder):
        self.folder = str(folder)

    def find_spec(self, name, path=None, target=None):
        if name == "yt_dlp" or name.startswith("yt_dlp."):
            return importlib.machinery.PathFinder.find_spec(name, [self.folder] if path is None else path)
        return None


def prefer_local(data_dir):
    """Make a downloaded yt-dlp win over the bundled one. Call before yt_dlp is imported."""
    folder = _dir(data_dir)
    if (folder / "yt_dlp").is_dir():
        sys.meta_path.insert(0, _LocalFinder(folder))


def _version_key(value):
    return tuple(int(part) for part in value.split(".") if part.isdigit())


def update_if_newer(data_dir, proxy=None):
    """Returns a short message for the log."""
    try:
        import yt_dlp.version
        current = yt_dlp.version.__version__
        handlers = [urllib.request.ProxyHandler({"https": proxy, "http": proxy})] if proxy else []
        opener = urllib.request.build_opener(*handlers)
        with opener.open(PYPI, timeout=20) as response:
            info = json.load(response)
        latest = info["info"]["version"]
        if _version_key(latest) <= _version_key(current):
            return f"yt-dlp {current} 已是最新版本"
        wheel = next(f for f in info["urls"] if f["packagetype"] == "bdist_wheel")
        with opener.open(wheel["url"], timeout=120) as response:
            data = response.read()
        staging = _dir(data_dir).with_name("ytdlp.new")
        shutil.rmtree(staging, ignore_errors=True)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if name.startswith("yt_dlp/"):
                    archive.extract(name, staging)
        target = _dir(data_dir)
        shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)
        return f"yt-dlp 已更新到 {latest}，下次同步生效"
    except Exception as exc:
        return f"yt-dlp 更新检查失败：{type(exc).__name__}"
