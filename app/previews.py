"""Local, cached display copies. Original media is never modified."""
import hashlib
import os
import shutil
import subprocess
import threading
from pathlib import Path

from PIL import Image, ImageOps

IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_TYPES = {".mp4", ".webm", ".mkv", ".mov"}


class PreviewCache:
    def __init__(self, root):
        self.root = Path(root) / "thumbnails"
        self.root.mkdir(parents=True, exist_ok=True)
        self.slots = threading.BoundedSemaphore(2)
        self.lock = threading.Lock()
        self.locks = {}

    def thumbnail(self, path):
        path = Path(path)
        stat = path.stat()
        key = hashlib.sha256(f"{path}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()
        target = self.root / (key + ".jpg")
        with self.lock:
            item_lock = self.locks.setdefault(key, threading.Lock())
        with item_lock:
            if target.is_file():
                return target
            with self.slots:
                temp = target.with_suffix(".part.jpg")
                try:
                    if path.suffix.lower() in VIDEO_TYPES:
                        ffmpeg = shutil.which("ffmpeg")
                        if not ffmpeg:
                            raise ValueError("未安装 FFmpeg，暂不能生成视频封面")
                        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                                        "-i", str(path), "-frames:v", "1", "-vf", "scale=640:-2",
                                        "-q:v", "4", str(temp)], check=True, timeout=25,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    else:
                        with Image.open(path) as original:
                            image = ImageOps.exif_transpose(original)
                            image.thumbnail((640, 1200))
                            if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                                rgba = image.convert("RGBA")
                                rgb = Image.new("RGB", rgba.size, "#171d24")
                                rgb.paste(rgba, mask=rgba.getchannel("A"))
                                image = rgb
                            else:
                                image = image.convert("RGB")
                            image.save(temp, "JPEG", quality=85, optimize=True)
                    temp.replace(target)
                finally:
                    temp.unlink(missing_ok=True)
        return target
