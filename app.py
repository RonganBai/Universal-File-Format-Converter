"""格式转换器 —— 拖入任意文件，点格式按钮即转换。输出到「输出根目录\\日期」文件夹。"""
import ctypes
import json
import os
import sys
import time
import traceback

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl, QPoint
from PyQt6.QtGui import QDesktopServices, QIcon, QPixmap, QCursor
from PyQt6.QtWidgets import (QApplication, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QStackedWidget, QVBoxLayout, QWidget, QProgressBar, QFrame)

import converter

HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
ASSETS = os.path.join(getattr(sys, "_MEIPASS", HERE), "assets")
CONFIG = os.path.join(os.environ.get("APPDATA", HERE), "格式转换器", "config.json")
DEFAULT_OUT = os.path.join(os.path.expanduser("~"), "格式转换输出")
FALLBACK_OUT = os.path.join(os.path.expanduser("~"), "Downloads", "格式转换输出")
BORDER = 6  # 窗口四周可拖拽缩放的宽度

QSS = """
#frame { background:#1f1f1f; border:1px solid #3d3d3d; border-radius:8px; }
#frame[max="true"] { border:none; border-radius:0; }
QWidget { color:#e6e6e6; font-family:"Microsoft YaHei UI"; font-size:14px; }
#title { background:transparent; }
#titleText { font-size:13px; color:#cfcfcf; }
#title QPushButton { background:transparent; border:none; border-radius:0; min-width:46px; max-width:46px;
                     min-height:34px; font-family:"Segoe Fluent Icons","Segoe MDL2 Assets"; font-size:10px; }
#title QPushButton:hover { background:#333; }
#title QPushButton#lang { font-family:"Microsoft YaHei UI"; font-size:12px; min-width:52px; max-width:52px; color:#cfcfcf; }
#title QPushButton#close:hover { background:#c42b1c; color:white; }
#cats QPushButton { text-align:left; padding:10px 12px; border:none; border-bottom:1px solid #333;
                    color:#aaa; background:transparent; border-radius:0; }
#cats QPushButton:checked { color:#fff; font-weight:bold; }
QPushButton#fmt { background:#333; border:1px solid #3c3c3c; border-radius:4px; min-width:76px; min-height:34px;
                  font-weight:bold; }
QPushButton#fmt:hover { background:#444; } QPushButton#fmt:pressed { background:#0a64c8; }
QPushButton#fmt:disabled { color:#666; }
QPushButton { background:#2d2d2d; border:1px solid #3c3c3c; border-radius:4px; padding:6px 12px; }
QPushButton:hover { background:#3a3a3a; }
QListWidget { background:#262626; border:1px dashed #555; border-radius:6px; }
QProgressBar { border:none; background:#2d2d2d; max-height:6px; border-radius:3px; }
QProgressBar::chunk { background:#0a84ff; border-radius:3px; }
QScrollBar:vertical { background:transparent; width:8px; } QScrollBar::handle:vertical { background:#444; border-radius:4px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; }
"""


LANG = "zh"
EN = {
    "格式转换器": "Format Converter",
    "① 拖入文件（任意类型，可多个，也可拖文件夹）": "① Drop files here (any type, multiple files or folders)",
    "添加文件": "Add files", "清空": "Clear",
    "更改输出目录…": "Change output…", "打开输出文件夹": "Open output folder",
    "② 选择目标格式（点击即开始转换）": "② Pick a target format (click to convert)",
    "图像": "Image", "文档": "Document", "向量": "Vector",
    "就绪": "Ready", "输出到：": "Output: ",
    "选择输出根目录（会按日期建子文件夹）": "Choose output root (dated subfolders are created inside)",
    "选择文件": "Choose files", "请先拖入或添加文件": "Please drop or add files first",
    "正在转换": "Converting", "完成：生成 {n} 个文件": "Done: {n} file(s) created",
    "打开所在文件夹": "Open folder", "失败：": "Failed: ",
    "切换语言": "Switch language",
    "blocked": "The output folder is blocked by Windows Controlled Folder Access; files were saved to {d}. "
               "Allow this app under Windows Security → Ransomware protection → Allow an app.",
    "blocked_zh": "输出目录被 Windows「受控文件夹访问」拦截，已改存到 {d}。可在 Windows 安全中心 → 勒索软件防护 → 允许应用 中放行本程序。",
    # 转换器报错
    "需要安装 DjVuLibre": "DJVU requires DjVuLibre (c44/djvm), see djvu.sourceforge.net",
    "需要 JBIG-KIT": "JBG requires pbmtojbg.exe from JBIG-KIT on PATH",
}


def tr(zh):
    if LANG == "en":
        return EN.get(zh, zh)
    return EN[zh + "_zh"] if zh + "_zh" in EN else zh


def tr_err(msg):
    if LANG == "en":
        for k in ("需要安装 DjVuLibre", "需要 JBIG-KIT"):
            if k in msg:
                return EN[k]
    return msg


def load_cfg():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=1)


def today_dir(root):
    d = os.path.join(root, time.strftime("%Y-%m-%d"))
    os.makedirs(d, exist_ok=True)
    return d


class Worker(QThread):
    progress = pyqtSignal(int, str)
    finished_all = pyqtSignal(list, list)

    def __init__(self, files, out_root, fmt, kind):
        super().__init__()
        self.files, self.out_root, self.fmt, self.kind = files, out_root, fmt, kind
        self.blocked = False

    def run(self):
        ok, bad = [], []
        for i, f in enumerate(self.files):
            self.progress.emit(i, f"{tr('正在转换')} {os.path.basename(f)} → {self.fmt} …")
            try:
                try:
                    ok += converter.convert(f, today_dir(self.out_root), self.fmt, self.kind)
                except (FileNotFoundError, PermissionError):
                    if not os.path.isdir(self.out_root):
                        raise
                    # 目录存在却写不进：多半是 Windows「受控文件夹访问」拦截，改存到「下载」
                    ok += converter.convert(f, today_dir(FALLBACK_OUT), self.fmt, self.kind)
                    self.blocked = True
            except Exception as e:
                traceback.print_exc()
                bad.append(f"{os.path.basename(f)}: {tr_err(str(e))}")
        self.finished_all.emit(ok, bad)


class TitleBar(QWidget):
    def __init__(self, win):
        super().__init__(objectName="title")
        self.win = win
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(QPixmap(os.path.join(ASSETS, "icon.png")).scaled(
            18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(ic)
        self.text = QLabel(objectName="titleText")
        lay.addWidget(self.text)
        lay.addStretch()
        self.btn_lang = QPushButton(objectName="lang")
        self.btn_lang.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_lang.clicked.connect(win.toggle_lang)
        lay.addWidget(self.btn_lang)
        self.btn_min = QPushButton("")
        self.btn_max = QPushButton("")
        self.btn_close = QPushButton("", objectName="close")
        self.btn_min.clicked.connect(win.showMinimized)
        self.btn_max.clicked.connect(win.toggle_max)
        self.btn_close.clicked.connect(win.close)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lay.addWidget(b)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.win.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        self.win.toggle_max()


class Main(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("格式转换器")
        self.setWindowIcon(QIcon(os.path.join(ASSETS, "icon.ico")))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.resize(760, 640)
        self.setMinimumSize(560, 520)
        self.cfg = load_cfg()
        global LANG
        LANG = self.cfg.get("lang", "zh")
        self.i18n = []  # (控件, 中文键, 后缀)
        self.out_root = self.cfg.get("out_root") or DEFAULT_OUT

        outer = QVBoxLayout(self)
        outer.setContentsMargins(BORDER, BORDER, BORDER, BORDER)
        self.frame = QFrame(objectName="frame")
        outer.addWidget(self.frame)
        fl = QVBoxLayout(self.frame)
        fl.setContentsMargins(1, 1, 1, 1)
        fl.setSpacing(0)
        self.title = TitleBar(self)
        fl.addWidget(self.title)
        body = QWidget()
        fl.addWidget(body, 1)
        root = QVBoxLayout(body)
        root.setContentsMargins(14, 6, 14, 12)

        root.addWidget(self.L(QLabel(), "① 拖入文件（任意类型，可多个，也可拖文件夹）"))
        self.list = QListWidget()
        root.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, fn in (("添加文件", self.add_files), ("清空", self.list.clear)):
            b = self.L(QPushButton(), text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        root.addLayout(row)

        orow = QHBoxLayout()
        self.dir_label = QLabel()
        self.dir_label.setStyleSheet("color:#999")
        orow.addWidget(self.dir_label, 1)
        for text, fn in (("更改输出目录…", self.pick_dir), ("打开输出文件夹", self.open_out)):
            b = self.L(QPushButton(), text)
            b.clicked.connect(fn)
            orow.addWidget(b)
        root.addLayout(orow)
        self.update_dir_label()

        root.addWidget(self.L(QLabel(), "② 选择目标格式（点击即开始转换）"))
        sel = QHBoxLayout()
        cats = QWidget(objectName="cats")
        cats.setFixedWidth(120)
        cl = QVBoxLayout(cats)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.stack = QStackedWidget()
        self.fmt_buttons = []
        groups = (("图像", "image", converter.IMAGE_FORMATS), ("文档", "doc", converter.DOC_FORMATS),
                  ("向量", "vector", converter.VECTOR_FORMATS))
        for idx, (name, kind, fmts) in enumerate(groups):
            cb = self.L(QPushButton(checkable=True, autoExclusive=True), name, "   ›")
            cb.clicked.connect(lambda _, i=idx: self.stack.setCurrentIndex(i))
            cb.setChecked(idx == 0)
            cl.addWidget(cb)
            page = QWidget()
            g = QGridLayout(page)
            g.setContentsMargins(8, 0, 0, 0)
            g.setSpacing(8)
            for k, f in enumerate(fmts):
                b = QPushButton(f, objectName="fmt")
                b.clicked.connect(lambda _, f=f, kind=kind: self.start(f, kind))
                g.addWidget(b, k // 5, k % 5)
                self.fmt_buttons.append(b)
            g.setRowStretch(g.rowCount(), 1)
            self.stack.addWidget(page)
        cl.addStretch()
        sel.addWidget(cats)
        sel.addWidget(self.stack, 1)
        root.addLayout(sel)

        self.bar = QProgressBar(textVisible=False)
        self.status = self.L(QLabel(), "就绪")
        self.status.setWordWrap(True)
        self.status.setOpenExternalLinks(True)
        root.addWidget(self.bar)
        root.addWidget(self.status)
        self.L(self.title.text, "格式转换器")
        self.retranslate()

    # ---- 语言
    def L(self, w, key, suffix=""):
        self.i18n.append((w, key, suffix))
        return w

    def retranslate(self):
        for w, key, suffix in self.i18n:
            w.setText(tr(key) + suffix)
        self.setWindowTitle(tr("格式转换器"))
        self.title.btn_lang.setText("EN" if LANG == "zh" else "中文")
        self.title.btn_lang.setToolTip(tr("切换语言"))
        self.update_dir_label()

    def toggle_lang(self):
        global LANG
        LANG = "en" if LANG == "zh" else "zh"
        self.cfg["lang"] = LANG
        save_cfg(self.cfg)
        self.i18n = [x for x in self.i18n if x[0] is not self.status] + [(self.status, "就绪", "")]
        self.retranslate()

    # ---- 窗口：最大化 / 边缘缩放
    def toggle_max(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def changeEvent(self, e):
        if hasattr(self, "frame"):
            m = self.isMaximized()
            self.layout().setContentsMargins(*(0 if m else BORDER,) * 4)
            self.frame.setProperty("max", m)
            self.frame.style().unpolish(self.frame)
            self.frame.style().polish(self.frame)
            self.title.btn_max.setText("" if m else "")
        super().changeEvent(e)

    def _edges(self, pos: QPoint):
        if self.isMaximized():
            return Qt.Edge(0)
        x, y, w, h, b = pos.x(), pos.y(), self.width(), self.height(), BORDER + 2
        e = Qt.Edge(0)
        if x < b: e |= Qt.Edge.LeftEdge
        if x > w - b: e |= Qt.Edge.RightEdge
        if y < b: e |= Qt.Edge.TopEdge
        if y > h - b: e |= Qt.Edge.BottomEdge
        return e

    def mouseMoveEvent(self, ev):
        e = self._edges(ev.position().toPoint())
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if e in (L | T, R | B):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif e in (R | T, L | B):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif e in (L, R):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif e in (T, B):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, ev):
        e = self._edges(ev.position().toPoint())
        if e and ev.button() == Qt.MouseButton.LeftButton:
            self.windowHandle().startSystemResize(e)

    # ---- 输出目录
    def update_dir_label(self):
        self.dir_label.setText(f"{tr('输出到：')}{self.out_root}\\{time.strftime('%Y-%m-%d')}")

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("选择输出根目录（会按日期建子文件夹）"), self.out_root)
        if d:
            self.out_root = os.path.normpath(d)
            self.cfg["out_root"] = self.out_root
            save_cfg(self.cfg)
            self.update_dir_label()

    def open_out(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(today_dir(self.out_root)))

    # ---- 文件
    def add_paths(self, paths):
        have = set(self.files())
        for p in paths:
            p = os.path.normpath(p)
            if os.path.isdir(p):
                for r, _, fs in os.walk(p):
                    self.add_paths([os.path.join(r, f) for f in fs])
            elif os.path.isfile(p) and p not in have:
                it = QListWidgetItem(f"{os.path.basename(p)}　　—　{os.path.dirname(p)}")
                it.setData(Qt.ItemDataRole.UserRole, p)
                it.setToolTip(p)
                self.list.addItem(it)
                have.add(p)

    def files(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def add_files(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("选择文件"))
        self.add_paths(fs)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls()])

    # ---- 转换
    def start(self, fmt, kind):
        files = self.files()
        if not files:
            self.status.setText(tr("请先拖入或添加文件"))
            return
        for b in self.fmt_buttons:
            b.setEnabled(False)
        self.bar.setRange(0, len(files))
        self.bar.setValue(0)
        self.worker = Worker(files, self.out_root, fmt, kind)
        self.worker.progress.connect(lambda i, t: (self.bar.setValue(i), self.status.setText(t)))
        self.worker.finished_all.connect(self.done)
        self.worker.start()

    def done(self, ok, bad):
        self.bar.setValue(self.bar.maximum())
        for b in self.fmt_buttons:
            b.setEnabled(True)
        msg = tr("完成：生成 {n} 个文件").format(n=len(ok))
        if ok:
            msg += (f'　<a href="{QUrl.fromLocalFile(os.path.dirname(ok[0])).toString()}" '
                    f'style="color:#4ea1ff">{tr("打开所在文件夹")}</a>')
        if self.worker.blocked:
            msg += "<br><span style='color:#e3b341'>" + tr("blocked").format(d=FALLBACK_OUT) + "</span>"
        if bad:
            msg += "<br><span style='color:#ff7b72'>" + tr("失败：") + "<br>".join(bad) + "</span>"
        self.status.setText(msg)
        self.update_dir_label()


if __name__ == "__main__":
    try:  # 让任务栏使用本程序自己的图标，而不是 Python 的
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GeShiZhuanHuanQi.App")
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(os.path.join(ASSETS, "icon.ico")))
    app.setStyleSheet(QSS)
    w = Main()
    w.add_paths(sys.argv[1:])
    w.show()
    sys.exit(app.exec())
