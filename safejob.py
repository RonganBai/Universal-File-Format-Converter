"""安全执行转换。

- 独立子进程（每个批量任务复用一个，省去重复启动）：Windows 作业对象限制内存、降低优先级，并校验限制是否真的生效
- 超时 / 取消时强制结束子进程；暂存目录写出，全部成功后再发布，不留半成品、不覆盖
- 生成清单：记录每个实际生成的文件，定时清理只处理清单中且未被改动的项目
"""
import ctypes
import json
import multiprocessing as mp
import os
import queue
import re
import shutil
import tempfile
import threading
import time
from ctypes import wintypes

import converter

TMP_ROOT = os.path.join(tempfile.gettempdir(), "FormatConverter_tmp")
STAGE_PREFIX = ".转换中_"
MANIFEST = os.path.join(os.environ.get("APPDATA", tempfile.gettempdir()), "格式转换器", "generated.json")
_lock = threading.Lock()
_reserved = set()
SLOTS = threading.BoundedSemaphore(2)   # 主窗口与悬浮球同时转换时，最多 2 个文件并行，控制 CPU 占用


class OutputBlocked(OSError):
    """输出目录无法写入（不存在、无权限或被「受控文件夹访问」拦截）。"""


class Cancelled(Exception):
    pass


def tmp_root():
    os.makedirs(TMP_ROOT, exist_ok=True)
    return TMP_ROOT


def _reserve(out_dir, title, ext):
    """在锁内挑一个不与已有文件、也不与其他进行中的任务冲突的名字。"""
    with _lock:
        n, name = 1, title
        while True:
            b = os.path.join(out_dir, name)
            if (b not in _reserved and not os.path.exists(b + ext) and not os.path.exists(b + "_001" + ext)
                    and not os.path.exists(b + "_files")):
                _reserved.add(b)
                return b
            n += 1
            name = f"{title} ({n})"


# ================================================================ 子进程
def _serve(req, res, settings):
    converter.SETTINGS.update(settings)
    while True:
        task = req.get()
        if task is None:
            return
        src, base, fmt, kind, params, tmpdir = task
        tempfile.tempdir = tmpdir
        try:
            res.put(("ok", converter.convert_into(src, base, fmt, kind, params)))
        except Exception as e:  # noqa: BLE001
            res.put(("err", str(e) or type(e).__name__))


class _BASIC(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", ctypes.c_uint32), ("SchedulingClass", ctypes.c_uint32)]


class _IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]


class _EXT(ctypes.Structure):
    _fields_ = [("Basic", _BASIC), ("Io", _IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


LIMIT_FLAGS = 0x100 | 0x2000 | 0x20   # 单进程内存上限 | 句柄关闭即结束 | 优先级


def _limit_process(pid, mem_mb):
    """把子进程放进作业对象并校验。返回 (作业句柄, 问题说明)；问题说明为空表示限制已生效。"""
    try:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.restype = wintypes.HANDLE
        k.OpenProcess.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                                ctypes.c_void_p]
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        k.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        job = k.CreateJobObjectW(None, None)
        if not job:
            return None, f"无法创建作业对象（错误 {ctypes.get_last_error()}）"
        info = _EXT()
        info.Basic.LimitFlags = LIMIT_FLAGS
        info.Basic.PriorityClass = 0x4000  # BELOW_NORMAL
        info.ProcessMemoryLimit = int(mem_mb) * 2 ** 20
        if not k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            return job, f"无法设置资源限制（错误 {ctypes.get_last_error()}）"
        hp = k.OpenProcess(0x0100 | 0x0001 | 0x1000, False, pid)  # SET_QUOTA | TERMINATE | QUERY_LIMITED
        if not hp:
            return job, f"无法打开处理进程（错误 {ctypes.get_last_error()}）"
        try:
            if not k.AssignProcessToJobObject(job, hp):
                return job, f"无法把处理进程放入作业对象（错误 {ctypes.get_last_error()}）"
            inside = wintypes.BOOL()
            got = _EXT()
            if (not k.IsProcessInJob(hp, job, ctypes.byref(inside)) or not inside.value
                    or not k.QueryInformationJobObject(job, 9, ctypes.byref(got), ctypes.sizeof(got), None)):
                return job, "无法确认资源限制"
            if (got.Basic.LimitFlags & LIMIT_FLAGS) != LIMIT_FLAGS or got.ProcessMemoryLimit != info.ProcessMemoryLimit:
                return job, "资源限制与设置不一致"
        finally:
            k.CloseHandle(hp)
        return job, ""
    except Exception as e:  # noqa: BLE001
        return None, f"资源限制失败：{e}"


class Runner:
    """一个批量任务对应一个处理子进程，按需启动，超时 / 取消时重启。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.p = self.req = self.res = self.job = None
        self.limit_problem = ""

    def _start(self):
        ctx = mp.get_context("spawn")
        self.req, self.res = ctx.Queue(), ctx.Queue()
        settings = {k: self.cfg[k] for k in ("strip_meta", "max_mb", "max_mpix", "max_unzip_mb")}
        self.p = ctx.Process(target=_serve, args=(self.req, self.res, settings), daemon=True)
        self.p.start()
        self.job, problem = _limit_process(self.p.pid, self.cfg["mem_mb"])
        if problem:
            self.limit_problem = problem

    def _kill(self):
        if self.p and self.p.is_alive():
            self.p.kill()
            self.p.join(3)
        if self.job:
            ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(self.job))
        self.p = self.job = None

    def run(self, task, cancel):
        if not self.p or not self.p.is_alive():
            self._start()
        self.req.put(task)
        deadline = time.time() + self.cfg["timeout_s"]
        while True:
            try:
                res = self.res.get(timeout=0.25)
                break
            except queue.Empty:
                if cancel is not None and cancel.is_set():
                    self._kill()
                    raise Cancelled()
                if not self.p.is_alive():
                    self._kill()
                    raise RuntimeError("处理进程异常退出（可能超出内存上限）")
                if time.time() > deadline:
                    self._kill()
                    raise TimeoutError(f"处理超过 {self.cfg['timeout_s']} 秒，已中止")
        if res[0] == "err":
            raise RuntimeError(res[1])
        return res[1]

    def close(self):
        if self.p and self.p.is_alive():
            try:
                self.req.put(None)
                self.p.join(2)
            except Exception:
                pass
        self._kill()


# ================================================================ 单个文件
def convert_one(src, out_dir, fmt, kind, cfg, params=None, runner=None, cancel=None):
    """转换一个文件：暂存目录写出 → 全部成功后移到输出目录 → 记入生成清单。返回 {files, meta, level, notes}。"""
    title = os.path.splitext(os.path.basename(src))[0]
    try:
        os.makedirs(out_dir, exist_ok=True)
        stage = tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=out_dir)
    except OSError as e:
        raise OutputBlocked(str(e)) from e
    final = _reserve(out_dir, title, converter.ext_of(fmt))
    tmpdir = tempfile.mkdtemp(dir=tmp_root())
    try:
        sbase = os.path.join(stage, os.path.basename(final))
        with SLOTS:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if cfg["isolate"]:
                own = runner is None
                runner = runner or Runner(cfg)
                try:
                    r = runner.run((src, sbase, fmt, kind, params, tmpdir), cancel)
                finally:
                    if own:
                        runner.close()
            else:
                converter.SETTINGS.update({k: cfg[k] for k in ("strip_meta", "max_mb", "max_mpix", "max_unzip_mb")})
                r = converter.convert_into(src, sbase, fmt, kind, params)
        published = []
        with _lock:
            for entry in os.listdir(stage):
                dst = os.path.join(out_dir, entry)
                if os.path.exists(dst):
                    raise FileExistsError(dst)
                os.rename(os.path.join(stage, entry), dst)
                published.append(dst)
        record(published)
        mp_ = lambda pth: os.path.join(out_dir, os.path.relpath(pth, stage))  # noqa: E731
        return {"files": [mp_(x) for x in r["files"]], "meta": {mp_(k): v for k, v in r["meta"].items()},
                "level": r["level"], "notes": r["notes"]}
    finally:
        with _lock:
            _reserved.discard(final)
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(tmpdir, ignore_errors=True)


# ================================================================ 生成清单
def _sig(path):
    st = os.stat(path)
    return {"size": st.st_size if not os.path.isdir(path) else -1, "mtime": round(st.st_mtime, 3)}


def _load_manifest():
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_manifest(items):
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    tmp = MANIFEST + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp, MANIFEST)


def record(paths):
    """记录由本程序生成的文件（含分享时打包的 ZIP）。"""
    now = time.time()
    with _lock:
        items = _load_manifest()
        for p in paths:
            try:
                items.append(dict(path=os.path.abspath(p), time=now, **_sig(p)))
            except OSError:
                pass
        _save_manifest(items)


def _unchanged(it):
    try:
        return _sig(it["path"]) == {"size": it["size"], "mtime": it["mtime"]}
    except OSError:
        return False


def expired_items(days):
    """清单中超过 days 天、仍存在且未被改动的生成文件（被改动或替换过的文件不会清理）。"""
    if days <= 0:
        return []
    cutoff = time.time() - days * 86400
    return [it["path"] for it in _load_manifest() if it["time"] < cutoff and _unchanged(it)]


def auto_delete(days):
    """把过期的生成文件移到回收站，并移除清单里已不存在的记录；返回移走的路径。"""
    done = []
    targets = set(expired_items(days))
    for p in targets:
        if to_recycle_bin(p):
            done.append(p)
    with _lock:
        items = [it for it in _load_manifest() if it["path"] not in done and os.path.exists(it["path"])]
        _save_manifest(items)
    for d in {os.path.dirname(p) for p in done}:  # 日期文件夹清空后顺手删掉空目录
        try:
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", os.path.basename(d)) and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass
    return done


# ================================================================ 清理
def clean_temp(out_root=None):
    """只清理本程序创建的临时文件：临时根目录 + 输出目录中残留的「.转换中_」暂存文件夹。返回清理数量。"""
    n = 0
    if os.path.isdir(TMP_ROOT):
        for e in os.listdir(TMP_ROOT):
            shutil.rmtree(os.path.join(TMP_ROOT, e), ignore_errors=True)
            n += 1
    if out_root and os.path.isdir(out_root):
        for d in os.listdir(out_root):
            dp = os.path.join(out_root, d)
            if os.path.isdir(dp) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
                for e in os.listdir(dp):
                    if e.startswith(STAGE_PREFIX):
                        shutil.rmtree(os.path.join(dp, e), ignore_errors=True)
                        n += 1
    return n


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


def to_recycle_bin(path):
    op = _SHFILEOPSTRUCTW(wFunc=3, pFrom=path + "\0", pTo=None,
                          fFlags=0x40 | 0x10 | 0x4 | 0x400)  # ALLOWUNDO | NOCONFIRMATION | SILENT | NOERRORUI
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not os.path.exists(path)
