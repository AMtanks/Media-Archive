"""FFmpeg is not bundled (≈95 MB). It is downloaded once into <data>/ffmpeg when first needed."""
import io
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path

URLS = (
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    "https://github.com/GyanD/codexffmpeg/releases/latest/download/ffmpeg-release-essentials.zip",
)


def folder(data_dir):
    return Path(data_dir) / "ffmpeg"


def add_to_path(data_dir):
    path = str(folder(data_dir))
    if path not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")


def ensure(data_dir, proxy=None, log=lambda message: None):
    """Return True when ffmpeg is usable, downloading it if necessary. Never raises."""
    add_to_path(data_dir)
    if shutil.which("ffmpeg"):
        return True
    handlers = [urllib.request.ProxyHandler({"https": proxy, "http": proxy})] if proxy else []
    opener = urllib.request.build_opener(*handlers)
    for url in URLS:
        try:
            log("正在下载 FFmpeg（约 30 MB，仅首次）…")
            with opener.open(url, timeout=60) as response:
                data = response.read()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                member = next(n for n in archive.namelist() if n.endswith("/bin/ffmpeg.exe"))
                target = folder(data_dir)
                target.mkdir(parents=True, exist_ok=True)
                partial = target / "ffmpeg.exe.part"
                with archive.open(member) as source, open(partial, "wb") as out:
                    shutil.copyfileobj(source, out)
                partial.replace(target / "ffmpeg.exe")
            log("FFmpeg 已就绪")
            return True
        except Exception as exc:
            log(f"FFmpeg 下载失败（{type(exc).__name__}）")
    return False
