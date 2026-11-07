"""Windows DPAPI: credentials can only be decrypted by the current Windows user."""
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, encrypt):
    if os.name != "nt":
        raise RuntimeError("登录凭证加密目前仅支持 Windows")
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if encrypt:
        ok = crypt.CryptProtectData(ctypes.byref(source), "X Archive", None, None, None, 1, ctypes.byref(target))
    else:
        ok = crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel.LocalFree(target.pbData)


class Vault:
    def __init__(self, root):
        self.path = Path(root) / "credentials.dpapi"

    def read(self):
        if not self.path.exists():
            return {}
        return json.loads(_dpapi(self.path.read_bytes(), False).decode("utf-8"))

    def save(self, auth_token, ct0=""):
        if not auth_token or len(auth_token) < 10 or any(c.isspace() for c in auth_token):
            raise ValueError("auth_token 格式不正确，请复制 Cookie 的值")
        payload = json.dumps({"auth_token": auth_token, "ct0": ct0}).encode("utf-8")
        temp = self.path.with_suffix(".tmp")
        temp.write_bytes(_dpapi(payload, True))
        temp.replace(self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)


class PlatformVault:
    """Platform cookies are isolated from X credentials and encrypted with Windows DPAPI."""
    def __init__(self, root, platform):
        if platform not in {'instagram', 'weibo'}:
            raise ValueError('不支持的平台')
        self.path = Path(root) / f'{platform}-credentials.dpapi'

    def read(self):
        if not self.path.exists():
            return {}
        return json.loads(_dpapi(self.path.read_bytes(), False).decode('utf-8'))

    def save(self, cookies):
        if not isinstance(cookies, dict) or not cookies:
            raise ValueError('没有可保存的登录凭证')
        temp = self.path.with_suffix('.tmp')
        temp.write_bytes(_dpapi(json.dumps(cookies, ensure_ascii=False).encode('utf-8'), True))
        temp.replace(self.path)

    def clear(self):
        self.path.unlink(missing_ok=True)
