"""对外联动：单实例、命令行转换、给其他软件（如「下载管家」）读的 integration.json。

约定（protocol 1）—— 其他软件只需要：
  1. 读 %APPDATA%\\格式转换器\\integration.json，拿到 command（启动命令）、quick（常用格式）、inputs（能处理的扩展名）；
  2. 启动  <command> [--to 目标] [--from 来源名] 文件1 文件2 …
     目标写法：PNG / image:PNG / preset:<预设 id>；不写 --to 则把文件加进主窗口列表。
转换器已在运行时，新启动的进程只把参数转交给它然后退出，不会出现第二个程序。
"""
import getpass
import hashlib
import json
import os
import sys

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

PROTOCOL = 1
KIND_ORDER = ("image", "doc", "sheet", "vector", "video")
# 各类常见的输入扩展名：其他软件据此决定要不要给某个文件显示「转换为」
INPUTS = {
    "image": ["png", "jpg", "jpeg", "jfif", "jpe", "webp", "gif", "bmp", "tif", "tiff", "heic", "heif", "avif", "ico",
              "cur", "dds", "tga", "psd", "jp2", "pcx", "ppm", "pgm", "exr", "hdr", "svg"],
    "doc": ["pdf", "doc", "docx", "docm", "dot", "dotx", "dotm", "odt", "rtf", "txt", "md", "html", "htm", "xps",
            "oxps", "epub", "djvu", "wps", "ppt", "pptx", "odp"],
    "sheet": ["xlsx", "xlsm", "xls", "ods", "csv", "tsv", "et"],
    "vector": ["ai", "eps", "ps", "wmf", "emf", "plt", "cgm", "fig", "sk", "sk1"],
    "video": ["mp4", "mov", "mkv", "webm", "avi", "wmv", "flv", "ts", "mts", "m2ts", "mpg", "mpeg", "3gp", "vob", "m4v"],
}


def server_name():
    """每个 Windows 用户（及配置目录）一个名字，不同用户互不干扰。"""
    try:
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USERNAME", "user")
    key = user + "|" + os.path.normcase(os.environ.get("APPDATA", ""))
    return "FormatConverter-" + hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()[:12]


def launch_command(here):
    """其他软件启动本程序用的命令。"""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, os.path.join(here, "app.py")]


# ---------------------------------------------------------------- 命令行
def parse_args(argv, cwd=None):
    """返回 {"to": 目标或 None, "source": 来源名, "paths": [...], "min": bool}；相对路径按 cwd 解析。"""
    to, source, paths, minimized = None, "", [], False
    it = iter(argv)
    for a in it:
        if a == "--to":
            to = next(it, None)
        elif a.startswith("--to="):
            to = a[5:]
        elif a == "--from":
            source = next(it, "") or ""
        elif a.startswith("--from="):
            source = a[7:]
        elif a == "--min":
            minimized = True
        elif a.startswith("--"):
            continue                       # 不认识的参数忽略，便于以后扩展
        else:
            paths.append(os.path.normpath(os.path.join(cwd, a)) if cwd and not os.path.isabs(a) else a)
    return {"to": (to or "").strip() or None, "source": source.strip()[:40], "paths": paths, "min": minimized}


def resolve_target(spec, formats, preset_by_id):
    """把 --to 的写法解析成 (fmt, kind, params, label)；无法识别返回 None。
    formats: {kind: [FMT, …]}；preset_by_id: 按 id 取预设的函数。"""
    if not spec:
        return None
    if spec.lower().startswith("preset:"):
        p = preset_by_id(spec.split(":", 1)[1])
        if not p:
            return None
        return p["fmt"], p["kind"], {k: p.get(k) for k in ("quality", "max_side", "pages", "vcodec") if p.get(k)}, p["name"]
    kind, _, fmt = spec.rpartition(":")
    fmt = fmt.strip().upper()
    fmt = {"JPG": "JPEG", "TIF": "TIFF"}.get(fmt, fmt)
    kinds = [kind.lower()] if kind else list(KIND_ORDER)
    for k in kinds:
        if fmt in formats.get(k, []):
            return fmt, k, None, fmt
    return None


# ---------------------------------------------------------------- 单实例
def forward_to_running(argv, timeout=1500):
    """已有实例在运行：把参数交给它并返回 True；没有则返回 False。"""
    sock = QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(timeout):
        return False
    data = json.dumps({"argv": list(argv), "cwd": os.getcwd()}, ensure_ascii=False).encode("utf-8") + b"\n"
    sock.write(data)
    sock.waitForBytesWritten(timeout)
    sock.disconnectFromServer()
    return True


class Server(QObject):
    """接收后启动进程转交过来的参数。只允许当前用户连接。"""
    received = pyqtSignal(list, str)   # argv, cwd

    def __init__(self, parent=None):
        super().__init__(parent)
        self.srv = QLocalServer(self)
        self.srv.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        name = server_name()
        if not self.srv.listen(name):
            QLocalServer.removeServer(name)      # 上次异常退出留下的残留
            self.srv.listen(name)
        self.srv.newConnection.connect(self._accept)

    def _accept(self):
        while self.srv.hasPendingConnections():
            s = self.srv.nextPendingConnection()
            buf = bytearray()

            def read(s=s, buf=buf):
                buf.extend(bytes(s.readAll()))
                if buf.endswith(b"\n") or len(buf) > 1 << 20:
                    s.readyRead.disconnect()
                    self._handle(bytes(buf))
                    s.disconnectFromServer()
            s.readyRead.connect(read)
            s.disconnected.connect(s.deleteLater)

    def _handle(self, raw):
        try:
            msg = json.loads(raw.decode("utf-8"))
            argv = [str(a) for a in msg.get("argv", [])][:5000]
            self.received.emit(argv, str(msg.get("cwd") or ""))
        except Exception:
            pass


# ---------------------------------------------------------------- integration.json
def build_info(version, here, lang, formats, quick):
    return {"app": "FormatConverter", "name": "格式转换器", "protocol": PROTOCOL, "version": version,
            "command": launch_command(here), "lang": lang,
            "quick": quick, "formats": formats, "inputs": INPUTS,
            "usage": "<command> [--to PNG | image:PNG | preset:<id>] [--from <name>] <files…>"}


def write_info(path, info):
    """内容有变化才写，先写临时文件再替换。"""
    data = json.dumps(info, ensure_ascii=False, indent=1)
    try:
        with open(path, encoding="utf-8") as f:
            if f.read() == data:
                return
    except OSError:
        pass
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        pass
