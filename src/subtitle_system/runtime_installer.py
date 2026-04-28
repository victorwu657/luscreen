from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
import zipfile
from typing import Any

import requests
from PySide6.QtCore import QThread, Signal

from src.utils import get_runtime_base_dir, get_runtime_data_dir


SUBTITLE_RUNTIME_INFO_URL = "https://luscreen.com/downloads/subtitle_runtime.json"


def get_subtitle_runtime_dir(base_dir: str | None = None) -> str:
    root = base_dir or get_runtime_data_dir()
    return os.path.join(root, "subtitle_runtime")


def _resolve_existing_runtime_dir(base_dir: str | None = None) -> str | None:
    runtime_dir = get_subtitle_runtime_dir(base_dir=base_dir)
    if os.path.isdir(runtime_dir):
        return runtime_dir
    if base_dir is None:
        alt = os.path.join(get_runtime_base_dir(), "subtitle_runtime")
        if os.path.isdir(alt):
            return alt
    return None


def _runtime_probe_paths(runtime_dir: str) -> list[str]:
    return [
        os.path.join(runtime_dir, "whisperx"),
        os.path.join(runtime_dir, "torch"),
        os.path.join(runtime_dir, "torch", "lib"),
        os.path.join(runtime_dir, "torchgen"),
    ]


def _is_runtime_complete(runtime_dir: str) -> bool:
    if not runtime_dir or (not os.path.isdir(runtime_dir)):
        return False
    for p in _runtime_probe_paths(runtime_dir):
        if not os.path.exists(p):
            return False
    return True


def ensure_subtitle_runtime_on_path(base_dir: str | None = None) -> bool:
    runtime_dir = _resolve_existing_runtime_dir(base_dir=base_dir)
    if not runtime_dir:
        return False
    try:
        if runtime_dir not in sys.path:
            sys.path.insert(0, runtime_dir)
    except Exception:
        return False

    try:
        torch_lib = os.path.join(runtime_dir, "torch", "lib")
        if os.path.isdir(torch_lib):
            os.environ["PATH"] = torch_lib + os.pathsep + (os.environ.get("PATH") or "")
            try:
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(torch_lib)
            except Exception:
                pass
    except Exception:
        pass
    return True


def is_subtitle_runtime_installed(base_dir: str | None = None) -> bool:
    runtime_dir = _resolve_existing_runtime_dir(base_dir=base_dir)
    if not runtime_dir:
        return False
    return _is_runtime_complete(runtime_dir)


def _read_bytes_from_url(url: str) -> bytes:
    u = (url or "").strip()
    if u.startswith("file://"):
        p = u[len("file://") :]
        with open(p, "rb") as f:
            return f.read()
    if os.path.exists(u):
        with open(u, "rb") as f:
            return f.read()

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }
    try:
        resp = requests.get(u, headers=headers, timeout=30)
    except (requests.exceptions.SSLError, OSError) as e:
        if "cacert.pem" in str(e) or "TLS CA certificate bundle" in str(e):
            resp = requests.get(u, headers=headers, timeout=30, verify=False)
        else:
            raise
    resp.raise_for_status()
    return resp.content


def _download_to_file(url: str, save_path: str, progress_cb=None):
    u = (url or "").strip()
    if u.startswith("file://") or os.path.exists(u):
        data = _read_bytes_from_url(u)
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(data)
        if progress_cb:
            progress_cb(100)
        return

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    }
    try:
        resp = requests.get(u, headers=headers, stream=True, timeout=60)
    except (requests.exceptions.SSLError, OSError) as e:
        if "cacert.pem" in str(e) or "TLS CA certificate bundle" in str(e):
            resp = requests.get(u, headers=headers, stream=True, timeout=60, verify=False)
        else:
            raise
    resp.raise_for_status()
    total = int(resp.headers.get("content-length", 0) or 0)
    done = 0
    os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
    with open(save_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            if not chunk:
                continue
            f.write(chunk)
            done += len(chunk)
            if total > 0 and progress_cb:
                progress_cb(min(99, int(done * 100 / total)))
    resp.close()
    if progress_cb:
        progress_cb(100)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def install_subtitle_runtime(*, info_url: str = SUBTITLE_RUNTIME_INFO_URL, base_dir: str | None = None, progress_cb=None) -> dict[str, Any]:
    root = base_dir or get_runtime_data_dir()
    runtime_dir = get_subtitle_runtime_dir(base_dir=root)
    downloads_dir = os.path.join(root, "downloads")
    os.makedirs(downloads_dir, exist_ok=True)

    raw = _read_bytes_from_url(info_url)
    try:
        meta = json.loads(raw.decode("utf-8", errors="ignore"))
    except Exception:
        raise RuntimeError("字幕组件清单解析失败。")

    pkg_url = str(meta.get("url") or "").strip()
    if not pkg_url:
        raise RuntimeError("字幕组件清单缺少 url。")
    version = str(meta.get("version") or "").strip() or "unknown"
    sha256_expected = str(meta.get("sha256") or "").strip().lower()

    zip_name = f"subtitle_runtime_{version}.zip"
    zip_path = os.path.join(downloads_dir, zip_name)

    if progress_cb:
        progress_cb(1)
    _download_to_file(pkg_url, zip_path, progress_cb=progress_cb)

    if not zipfile.is_zipfile(zip_path):
        raise RuntimeError("字幕组件包不是有效的 ZIP 文件。")

    if sha256_expected:
        got = _sha256_file(zip_path)
        if got.lower() != sha256_expected:
            raise RuntimeError("字幕组件包校验失败（sha256 不匹配）。")

    tmp_extract = os.path.join(downloads_dir, f"subtitle_runtime_extract_{int(time.time())}")
    if os.path.exists(tmp_extract):
        shutil.rmtree(tmp_extract, ignore_errors=True)
    os.makedirs(tmp_extract, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(tmp_extract)

    items = []
    try:
        items = os.listdir(tmp_extract)
    except Exception:
        items = []
    extracted_root = tmp_extract
    if len(items) == 1:
        one = os.path.join(tmp_extract, items[0])
        if os.path.isdir(one):
            extracted_root = one

    new_runtime = os.path.join(downloads_dir, f"subtitle_runtime_new_{int(time.time())}")
    if os.path.exists(new_runtime):
        shutil.rmtree(new_runtime, ignore_errors=True)
    shutil.move(extracted_root, new_runtime)
    if not _is_runtime_complete(new_runtime):
        raise RuntimeError("字幕组件包内容不完整（缺少 whisperx/torch/torchgen/torch/lib）。")

    if os.path.exists(tmp_extract):
        shutil.rmtree(tmp_extract, ignore_errors=True)

    old_runtime = None
    if os.path.exists(runtime_dir):
        old_runtime = os.path.join(downloads_dir, f"subtitle_runtime_old_{int(time.time())}")
        try:
            if os.path.exists(old_runtime):
                shutil.rmtree(old_runtime, ignore_errors=True)
            shutil.move(runtime_dir, old_runtime)
        except Exception:
            shutil.rmtree(runtime_dir, ignore_errors=True)
            old_runtime = None

    shutil.move(new_runtime, runtime_dir)

    try:
        if old_runtime and os.path.exists(old_runtime):
            shutil.rmtree(old_runtime, ignore_errors=True)
    except Exception:
        pass

    ensure_subtitle_runtime_on_path(base_dir=root)
    return {"ok": True, "version": version, "dir": runtime_dir}


class SubtitleRuntimeDownloadWorker(QThread):
    progress = Signal(int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, *, info_url: str = SUBTITLE_RUNTIME_INFO_URL):
        super().__init__()
        self.info_url = info_url

    def run(self):
        try:
            def cb(p: int):
                self.progress.emit(int(p))

            r = install_subtitle_runtime(info_url=self.info_url, progress_cb=cb)
            self.finished_ok.emit(str(r.get("version") or ""))
        except Exception as e:
            self.failed.emit(str(e))
