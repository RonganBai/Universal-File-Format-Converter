"""格式转换器 —— 拖入任意文件，点格式按钮即转换。输出到「输出根目录\\日期」文件夹。"""
import ctypes
import json
import os
import subprocess
import sys
import time
import traceback
import zipfile

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl, QPoint, QTimer, QMimeData, QFileInfo, QSize
from PyQt6.QtGui import QDesktopServices, QIcon, QPixmap, QKeySequence, QShortcut, QAction
from PyQt6.QtWidgets import (QApplication, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QStackedWidget, QVBoxLayout, QWidget, QProgressBar, QFrame,
                             QDialog, QCheckBox, QDialogButtonBox, QRadioButton, QSystemTrayIcon, QMenu,
                             QFileIconProvider, QAbstractItemView, QTextBrowser)

import converter

VERSION = "1.4.1"
HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
ASSETS = os.path.join(getattr(sys, "_MEIPASS", HERE), "assets")
CONFIG = os.path.join(os.environ.get("APPDATA", HERE), "格式转换器", "config.json")
DEFAULT_OUT = os.path.join(os.path.expanduser("~"), "格式转换输出")
FALLBACK_OUT = os.path.join(os.path.expanduser("~"), "Downloads", "格式转换输出")
BORDER = 6  # 窗口四周可拖拽缩放的宽度
IMG_EXT = {"png", "jpg", "jpeg", "bmp", "gif", "webp", "ico", "tif", "tiff"}

QSS = """
#frame { background:#1b1b1b; border:1px solid #3d3d3d; border-radius:8px; }
#frame[max="true"] { border:none; border-radius:0; }
QWidget { color:#e6e6e6; font-family:"Microsoft YaHei UI"; font-size:13px; }
#title { background:transparent; }
#titleText { font-size:13px; color:#cfcfcf; }
#version { font-size:11px; color:#7d7d7d; }
#title QPushButton { background:transparent; border:none; border-radius:0; min-width:46px; max-width:46px;
                     min-height:34px; font-family:"Segoe Fluent Icons","Segoe MDL2 Assets"; font-size:10px; }
#title QPushButton:hover { background:#333; }
#title QPushButton#lang { font-family:"Microsoft YaHei UI"; font-size:12px; min-width:52px; max-width:52px; color:#cfcfcf; }
#title QPushButton#close:hover { background:#c42b1c; color:white; }
#card { background:#242424; border:1px solid #343434; border-radius:10px; }
#card[hl="true"] { border:2px solid #0a84ff; }
#cardTitle { font-size:14px; font-weight:bold; color:#ffffff; }
#hint { color:#8d8d8d; font-size:12px; }
#cats QPushButton { text-align:left; padding:9px 12px; border:none; border-radius:6px;
                    color:#aaa; background:transparent; }
#cats QPushButton:hover { background:#2e2e2e; }
#cats QPushButton:checked { color:#fff; font-weight:bold; background:#0a3d75; }
QPushButton#fmt { background:#323232; border:1px solid #3c3c3c; border-radius:5px; min-width:56px; padding:0; min-height:32px;
                  font-weight:bold; }
QPushButton#fmt:hover { background:#444; } QPushButton#fmt:pressed { background:#0a64c8; }
QPushButton#fmt:disabled { color:#666; }
QPushButton { background:#2f2f2f; border:1px solid #3c3c3c; border-radius:5px; padding:5px 11px; }
QPushButton:hover { background:#3a3a3a; }
QPushButton:disabled { color:#666; }
QPushButton#primary { background:#0a64c8; border-color:#0a64c8; color:white; }
QPushButton#primary:hover { background:#0a84ff; }
QListWidget { background:#1c1c1c; border:1px dashed #4a4a4a; border-radius:6px; outline:none; }
QListWidget#results { border:1px solid #333; }
QListWidget::item { padding:3px; border-radius:4px; }
QListWidget::item:selected { background:#0a3d75; color:white; }
QListWidget::item:hover { background:#2c2c2c; }
QProgressBar { border:none; background:#2d2d2d; max-height:6px; border-radius:3px; }
QProgressBar::chunk { background:#0a84ff; border-radius:3px; }
QScrollBar:vertical { background:transparent; width:8px; } QScrollBar::handle:vertical { background:#444; border-radius:4px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; }
QMenu { background:#2b2b2b; color:#eee; border:1px solid #444; }
QMenu::item { padding:6px 22px; } QMenu::item:selected { background:#0a84ff; }
QMenu::separator { height:1px; background:#444; margin:4px 8px; }
QToolTip { background:#2b2b2b; color:#eee; border:1px solid #555; }
QDialog { background:#1f1f1f; }
QTextBrowser { background:#1c1c1c; border:1px solid #333; border-radius:6px; }
"""


LANG = "zh"
EN = {
    "格式转换器": "Format Converter",
    "添加文件": "Add files", "添加文件夹": "Add folder", "清空": "Clear", "移除所选": "Remove selected",
    "更改输出目录…": "Change output…", "打开输出文件夹": "Open output folder",
    "图像": "Image", "文档": "Document", "表格": "Spreadsheet", "向量": "Vector",
    "就绪": "Ready", "输出到：": "Output: ",
    "选择输出根目录（会按日期建子文件夹）": "Choose output root (dated subfolders are created inside)",
    "选择文件": "Choose files", "请先拖入或添加文件": "Please drop or add files first",
    "正在转换": "Converting", "完成：生成 {n} 个文件": "Done: {n} file(s) created",
    "打开所在文件夹": "Open folder", "失败：": "Failed: ",
    "切换语言": "Switch language",
    "悬浮球设置…": "Floating ball…", "悬浮球设置": "Floating ball settings",
    "选择常用格式（最多 6 种）：已选 {n}/6": "Pick quick formats (max 6): {n}/6 selected",
    "确定": "OK", "取消": "Cancel", "打开主窗口": "Open main window", "退出": "Quit",
    "在屏幕边缘显示悬浮球": "Show a floating ball at the screen edge", "关闭主窗口时：": "When closing the main window:",
    "完全退出": "Quit completely", "隐藏到系统托盘，保留悬浮球": "Hide to the system tray, keep the floating ball",
    "转换中…": "Converting…",
    "文件转换": "File Convert", "拖入文件": "Drop files", "松开后选择目标格式": "then pick a format",
    "右键设置常用格式": "Right-click to set formats", "已拖入 {n} 个文件": "{n} file(s) added",
    "…等 {n} 个": "…{n} in total", "选择要转换成的格式": "Choose a target format",
    "正在转换为 {f}…": "Converting to {f}…", "完成 {n} 个": "{n} done", "失败 {n} 个": "{n} failed",
    "移除": "Remove", "编辑常用格式": "Edit quick formats", "清空文件": "Clear files",
    # 模块
    "① 输入文件": "① Input files", "② 目标格式": "② Target format", "③ 转换结果": "③ Results",
    "拖入文件或文件夹到窗口任意位置（可多选，Delete 键移除）":
        "Drop files or folders anywhere in the window (multi-select, Delete to remove)",
    "点击格式即开始批量转换列表中的全部文件": "Click a format to convert every file in the list",
    "双击文件直接打开；可多选后批量打开、定位或分享": "Double-click to open; multi-select to open, locate or share in bulk",
    "共 {n} 个文件": "{n} file(s)", "共 {n} 个结果": "{n} result(s)",
    "打开": "Open", "定位": "Show in folder", "分享": "Share", "全选": "Select all", "清空记录": "Clear list",
    "请先选择结果文件": "Select result files first",
    "Windows 共享…": "Windows Share…", "复制文件（可粘贴到微信 / QQ / 邮件）": "Copy files (paste into chat / email)",
    "复制文件路径": "Copy file paths", "打包为 ZIP 并定位": "Pack into a ZIP and show it",
    "已复制 {n} 个文件，可直接粘贴发送": "Copied {n} file(s) — paste to send",
    "已复制路径": "Paths copied", "已打包：{p}": "Packed: {p}",
    "多个文件已打包为 ZIP 再共享": "Multiple files were packed into one ZIP for sharing",
    # 托盘 / 帮助
    "显示悬浮球": "Show floating ball", "使用引导": "Quick tour", "帮助手册": "Help manual", "帮助": "Help",
    "已最小化到系统托盘": "Minimized to the system tray",
    "格式转换器仍在后台运行，右键托盘图标可快速打开功能。":
        "Format Converter keeps running. Right-click the tray icon for quick actions.",
    "上一步": "Back", "下一步": "Next", "跳过": "Skip", "开始使用": "Get started",
    "blocked": "The output folder is blocked by Windows Controlled Folder Access; files were saved to {d}. "
               "Allow this app under Windows Security → Ransomware protection → Allow an app.",
    "blocked_zh": "输出目录被 Windows「受控文件夹访问」拦截，已改存到 {d}。可在 Windows 安全中心 → 勒索软件防护 → 允许应用 中放行本程序。",
    # 转换器报错
    "需要安装 DjVuLibre": "DJVU requires DjVuLibre (c44/djvm), see djvu.sourceforge.net",
    "需要 JBIG-KIT": "JBG requires pbmtojbg.exe from JBIG-KIT on PATH",
}

GUIDE = {
    "zh": [
        ("欢迎使用格式转换器", "只需三步：拖入文件 → 点击目标格式 → 在结果里打开或分享。下面带你认识每个模块。", None),
        ("① 输入文件", "把文件或文件夹拖到窗口任意位置，或点「添加文件」。支持多选，选中后按 Delete 或「移除所选」可删掉。", "in"),
        ("② 目标格式", "左侧选分类（图像 / 文档 / 表格 / 向量），右侧点一个格式，列表里的全部文件会一起转换。", "fmt"),
        ("③ 转换结果", "转换好的文件显示在这里：双击直接打开，多选后可批量打开、定位到文件夹或分享。", "out"),
        ("悬浮球与托盘", "在「悬浮球设置」里开启屏幕边缘悬浮球，把文件拖到气泡上就能快速转换。"
                         "关闭窗口时程序可隐藏到右下角托盘，右键托盘图标即可打开各项功能。标题栏的「?」随时查看帮助。", None),
    ],
    "en": [
        ("Welcome to Format Converter", "Three steps: drop files → click a target format → open or share the results. "
                                        "Here is a quick look at each panel.", None),
        ("① Input files", "Drop files or folders anywhere in the window, or click “Add files”. Select several and press "
                          "Delete or “Remove selected” to take them out.", "in"),
        ("② Target format", "Pick a category on the left (Image / Document / Spreadsheet / Vector), then click a format. "
                            "Every file in the list is converted.", "fmt"),
        ("③ Results", "Converted files appear here. Double-click to open; multi-select to open, show in folder or share.", "out"),
        ("Floating ball & tray", "Turn on the screen-edge floating ball in “Floating ball…” and drop files on it for quick "
                                 "conversions. When the window is closed the app can hide in the system tray — right-click "
                                 "its icon for quick actions. Click “?” in the title bar for help at any time.", None),
    ],
}

HELP_ZH = """
<h2>格式转换器 帮助手册</h2>
<h3>1. 基本流程</h3>
<ol><li><b>添加文件</b>：拖到窗口任意位置，或点「添加文件」「添加文件夹」。文件夹会递归加入其中所有文件。</li>
<li><b>选择格式</b>：在「② 目标格式」左侧选分类，点击格式按钮立即开始转换列表中的<b>全部</b>文件。</li>
<li><b>查看结果</b>：结果出现在「③ 转换结果」，同时保存在输出文件夹。</li></ol>
<h3>2. 输入文件</h3>
<ul><li>任意类型都可以拖入：图片、PDF、Word/ODT、Excel/CSV、文本、音视频等；无法识别内容的文件会生成文件信息预览。</li>
<li>按住 Ctrl / Shift 多选，按 <b>Delete</b> 或「移除所选」删除；「清空」移除全部。</li></ul>
<h3>3. 目标格式</h3>
<ul><li><b>图像</b>：PNG、JPG、WEBP、TIFF、ICO、HEIC 等 30 种。多页文档会按页输出多张图片。</li>
<li><b>文档</b>：PDF、DOCX、DOC、RTF、ODT、TXT、HTML、XPS 等。PDF 中的表格会尽量保留为表格。</li>
<li><b>表格</b>：XLSX、XLSM、CSV。PDF / Word 中识别出的表格各放一张工作表，合并单元格会保留。</li>
<li><b>向量</b>：SVG、AI、EPS、PS、EMF、WMF 等 11 种；PDF→SVG/AI 为真矢量，其他来源会嵌入图像。</li>
<li>DJVU 需要安装 DjVuLibre，JBG 需要 JBIG-KIT 的 pbmtojbg。</li></ul>
<h3>4. 转换结果</h3>
<ul><li><b>双击</b>文件直接用默认程序打开。</li>
<li>多选后可批量 <b>打开</b>、<b>定位</b>（在资源管理器中选中）或 <b>分享</b>。</li>
<li>分享方式：Windows 共享面板；复制文件后在微信 / QQ / 邮件中直接粘贴；复制路径；打包为 ZIP。多个文件使用 Windows 共享时会先打包成一个 ZIP。</li>
<li>「清空记录」只清除列表，不会删除文件。</li></ul>
<h3>5. 输出位置</h3>
<ul><li>默认输出到 <code>用户目录\\格式转换输出\\日期</code>，可点「更改输出目录…」修改根目录，每天自动建新的日期文件夹。</li>
<li>同名文件不会被覆盖，会自动加序号。</li>
<li>如果输出目录被 Windows「受控文件夹访问」拦截，会改存到「下载\\格式转换输出」并提示。</li></ul>
<h3>6. 悬浮球</h3>
<ul><li>在「悬浮球设置…」中开启，可吸附在屏幕左、右、顶部边缘，拖动即可换位置。</li>
<li>把文件拖到气泡上 → 显示已拖入的文件，每个文件右侧的 ✕ 可单独移除 → 点击常用格式即转换，完成后自动打开输出文件夹。</li>
<li>选择格式时点 <b>✎</b> 可快速编辑常用的 6 种格式；右上角 ✕ 清空已拖入文件。</li>
<li>右键悬浮球可打开主窗口、设置、输出文件夹或退出。</li></ul>
<h3>7. 系统托盘</h3>
<ul><li>程序运行时右下角托盘会显示图标，单击 / 双击打开主窗口，右键可快速添加文件、打开输出文件夹、开关悬浮球、查看引导与帮助、退出。</li>
<li>开启悬浮球并把「关闭主窗口时」设为「隐藏到系统托盘」后，点 ✕ 只会隐藏窗口；否则会完全退出。</li></ul>
<h3>8. 其他</h3>
<ul><li>标题栏「EN / 中文」切换语言，「?」打开本手册，托盘菜单「使用引导」可重新查看新手引导。</li>
<li>设置保存在 <code>%APPDATA%\\格式转换器\\config.json</code>。</li></ul>
"""

HELP_EN = """
<h2>Format Converter — Help</h2>
<h3>1. Basics</h3>
<ol><li><b>Add files</b>: drop them anywhere in the window, or use “Add files” / “Add folder” (folders are added recursively).</li>
<li><b>Pick a format</b>: choose a category in “② Target format” and click a format — <b>all</b> listed files are converted.</li>
<li><b>See results</b>: they appear in “③ Results” and are saved in the output folder.</li></ol>
<h3>2. Input files</h3>
<ul><li>Any type can be dropped: images, PDF, Word/ODT, Excel/CSV, text, audio/video… Unknown files produce an info preview.</li>
<li>Use Ctrl / Shift to multi-select, then <b>Delete</b> or “Remove selected”; “Clear” removes everything.</li></ul>
<h3>3. Target formats</h3>
<ul><li><b>Image</b>: 30 formats incl. PNG, JPG, WEBP, TIFF, ICO, HEIC. Multi-page documents give one image per page.</li>
<li><b>Document</b>: PDF, DOCX, DOC, RTF, ODT, TXT, HTML, XPS… Tables in PDFs are kept as tables where possible.</li>
<li><b>Spreadsheet</b>: XLSX, XLSM, CSV. Each table found in a PDF / Word file becomes a sheet; merged cells are kept.</li>
<li><b>Vector</b>: 11 formats incl. SVG, AI, EPS, PS, EMF, WMF. PDF→SVG/AI is true vector; other sources embed an image.</li>
<li>DJVU needs DjVuLibre; JBG needs pbmtojbg from JBIG-KIT.</li></ul>
<h3>4. Results</h3>
<ul><li><b>Double-click</b> a file to open it.</li>
<li>Multi-select to <b>Open</b>, <b>Show in folder</b> or <b>Share</b> in bulk.</li>
<li>Sharing: Windows Share panel; copy files and paste them into chat or email; copy paths; pack into a ZIP. Several files are packed into one ZIP for Windows Share.</li>
<li>“Clear list” only clears the list — files are not deleted.</li></ul>
<h3>5. Output location</h3>
<ul><li>Default: <code>%USERPROFILE%\\格式转换输出\\date</code>. Change the root with “Change output…”; a dated folder is created each day.</li>
<li>Existing files are never overwritten — a number is appended.</li>
<li>If Windows Controlled Folder Access blocks the folder, files go to <code>Downloads\\格式转换输出</code> instead.</li></ul>
<h3>6. Floating ball</h3>
<ul><li>Enable it in “Floating ball…”. It docks to the left, right or top edge — drag it to move.</li>
<li>Drop files on the bubble → the files are listed (✕ next to each removes it) → click a quick format; the output folder opens when done.</li>
<li>Click <b>✎</b> while choosing to edit the 6 quick formats; the top-right ✕ clears the dropped files.</li>
<li>Right-click the ball for the main window, settings, output folder or Quit.</li></ul>
<h3>7. System tray</h3>
<ul><li>A tray icon appears while the app runs. Click it to open the window; right-click to add files, open the output folder, toggle the ball, see the tour / help, or quit.</li>
<li>With the ball on and “When closing” set to hide, ✕ only hides the window; otherwise the app quits.</li></ul>
<h3>8. Misc</h3>
<ul><li>“EN / 中文” switches the language, “?” opens this manual, and “Quick tour” in the tray menu replays the tour.</li>
<li>Settings live in <code>%APPDATA%\\格式转换器\\config.json</code>.</li></ul>
"""


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


def windows_share(path):
    """调出 Windows 共享面板（资源管理器右键菜单里的「共享」）。"""
    ps = ("$f=(New-Object -ComObject Shell.Application).Namespace($args[0]).ParseName($args[1]);"
          "$f.InvokeVerb('Windows.ModernShare'); Start-Sleep -Seconds 120")
    subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps,
                      os.path.dirname(path), os.path.basename(path)],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def show_in_folder(paths):
    if not paths:
        return
    if len(paths) == 1:
        subprocess.Popen(f'explorer /select,"{paths[0]}"')
        return
    os.startfile(os.path.dirname(paths[0]))


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
        lay.addWidget(QLabel("v" + VERSION, objectName="version"))
        lay.addStretch()
        self.btn_help = QPushButton("?", objectName="lang")
        self.btn_help.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_help.clicked.connect(win.open_help)
        lay.addWidget(self.btn_help)
        self.btn_lang = QPushButton(objectName="lang")
        self.btn_lang.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_lang.clicked.connect(win.toggle_lang)
        lay.addWidget(self.btn_lang)
        self.btn_min = QPushButton("\ue921")
        self.btn_max = QPushButton("\ue922")
        self.btn_close = QPushButton("\ue8bb", objectName="close")
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


class FileList(QListWidget):
    """支持多选、Delete 删除的列表。"""
    def __init__(self, deletable=True, **kw):
        super().__init__(**kw)
        self.deletable = deletable
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setIconSize(QSize(28, 28))

    def keyPressEvent(self, e):
        if self.deletable and e.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            for it in self.selectedItems():
                self.takeItem(self.row(it))
            self.model().layoutChanged.emit()
            return
        super().keyPressEvent(e)


class Main(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("格式转换器")
        self.setWindowIcon(QIcon(os.path.join(ASSETS, "icon.ico")))
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.resize(900, 700)
        self.setMinimumSize(720, 600)
        self.cfg = load_cfg()
        global LANG
        LANG = self.cfg.get("lang", "zh")
        self.i18n = []  # (控件, 中文键, 后缀)
        self.ball = None
        self.jobs = []
        self.icons = QFileIconProvider()
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
        root.setContentsMargins(12, 4, 12, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        root.addLayout(top, 5)

        # ---- ① 输入文件
        self.card_in, v = self.card("① 输入文件", "拖入文件或文件夹到窗口任意位置（可多选，Delete 键移除）")
        self.list = FileList()
        self.list.model().rowsInserted.connect(self.update_counts)
        self.list.model().rowsRemoved.connect(self.update_counts)
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, fn, obj in (("添加文件", self.add_files, "primary"), ("添加文件夹", self.add_folder, ""),
                              ("移除所选", self.remove_selected, ""), ("清空", self.list.clear, "")):
            b = self.L(QPushButton(objectName=obj), text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        self.in_count = QLabel(objectName="hint")
        row.addWidget(self.in_count)
        v.addLayout(row)
        top.addWidget(self.card_in, 1)

        # ---- ③ 转换结果（输出）
        self.card_out, v = self.card("③ 转换结果", "双击文件直接打开；可多选后批量打开、定位或分享")
        orow = QHBoxLayout()
        self.dir_label = QLabel(objectName="hint")
        self.dir_label.setWordWrap(True)
        orow.addWidget(self.dir_label, 1)
        for text, fn in (("更改输出目录…", self.pick_dir), ("打开输出文件夹", self.open_out)):
            b = self.L(QPushButton(), text)
            b.clicked.connect(fn)
            orow.addWidget(b)
        v.addLayout(orow)
        self.results = FileList(deletable=True, objectName="results")
        self.results.itemDoubleClicked.connect(lambda it: os.startfile(it.data(Qt.ItemDataRole.UserRole)))
        self.results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self.results_menu)
        self.results.model().rowsInserted.connect(self.update_counts)
        self.results.model().rowsRemoved.connect(self.update_counts)
        v.addWidget(self.results, 1)
        rrow = QHBoxLayout()
        self.btn_open = self.L(QPushButton(), "打开")
        self.btn_open.clicked.connect(self.open_selected)
        self.btn_locate = self.L(QPushButton(), "定位")
        self.btn_locate.clicked.connect(lambda: show_in_folder(self.selected_results()))
        self.btn_share = self.L(QPushButton(objectName="primary"), "分享", " ▾")
        self.btn_share.clicked.connect(lambda: self.share_menu().exec(
            self.btn_share.mapToGlobal(QPoint(0, self.btn_share.height()))))
        self.btn_all = self.L(QPushButton(), "全选")
        self.btn_all.clicked.connect(self.results.selectAll)
        self.btn_clr = self.L(QPushButton(), "清空记录")
        self.btn_clr.clicked.connect(self.results.clear)
        for b in (self.btn_open, self.btn_locate, self.btn_share, self.btn_all, self.btn_clr):
            rrow.addWidget(b)
        rrow.addStretch()
        self.out_count = QLabel(objectName="hint")
        rrow.addWidget(self.out_count)
        v.addLayout(rrow)
        self.bar = QProgressBar(textVisible=False)
        v.addWidget(self.bar)
        self.status = self.L(QLabel(), "就绪")
        self.status.setWordWrap(True)
        self.status.setOpenExternalLinks(True)
        v.addWidget(self.status)
        top.addWidget(self.card_out, 1)

        # ---- ② 目标格式
        self.card_fmt, v = self.card("② 目标格式", "点击格式即开始批量转换列表中的全部文件")
        sel = QHBoxLayout()
        cats = QWidget(objectName="cats")
        cats.setFixedWidth(130)
        cl = QVBoxLayout(cats)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(2)
        self.stack = QStackedWidget()
        self.fmt_buttons = []
        groups = (("图像", "image", converter.IMAGE_FORMATS), ("文档", "doc", converter.DOC_FORMATS),
                  ("表格", "sheet", converter.SHEET_FORMATS), ("向量", "vector", converter.VECTOR_FORMATS))
        for idx, (name, kind, fmts) in enumerate(groups):
            cb = self.L(QPushButton(checkable=True, autoExclusive=True), name, f"  ({len(fmts)})")
            cb.clicked.connect(lambda _, i=idx: self.stack.setCurrentIndex(i))
            cb.setChecked(idx == 0)
            cl.addWidget(cb)
            page = QWidget()
            g = QGridLayout(page)
            g.setContentsMargins(6, 0, 0, 0)
            g.setSpacing(7)
            for k, f in enumerate(fmts):
                b = QPushButton(f, objectName="fmt")
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _, f=f, kind=kind: self.start(f, kind))
                g.addWidget(b, k // 8, k % 8)
                self.fmt_buttons.append(b)
            g.setRowStretch(g.rowCount(), 1)
            self.stack.addWidget(page)
        cl.addStretch()
        sel.addWidget(cats)
        line = QFrame()
        line.setFixedWidth(1)
        line.setStyleSheet("background:#383838")
        sel.addWidget(line)
        sel.addWidget(self.stack, 1)
        v.addLayout(sel, 1)
        root.addWidget(self.card_fmt, 4)

        self.L(self.title.text, "格式转换器")
        QShortcut(QKeySequence("F1"), self, self.open_help)
        self.make_tray()
        self.retranslate()

    def card(self, title, hint):
        f = QFrame(objectName="card")
        v = QVBoxLayout(f)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        v.addWidget(self.L(QLabel(objectName="cardTitle"), title))
        hl = self.L(QLabel(objectName="hint"), hint)
        hl.setWordWrap(True)
        v.addWidget(hl)
        return f, v

    def highlight(self, which):
        for key, c in (("in", self.card_in), ("fmt", self.card_fmt), ("out", self.card_out)):
            c.setProperty("hl", key == which)
            c.style().unpolish(c)
            c.style().polish(c)

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
        self.title.btn_help.setToolTip(tr("帮助手册") + " (F1)")
        self.update_dir_label()
        self.update_counts()
        self.build_tray_menu()

    def toggle_lang(self):
        global LANG
        LANG = "en" if LANG == "zh" else "zh"
        self.cfg["lang"] = LANG
        save_cfg(self.cfg)
        self.i18n = [x for x in self.i18n if x[0] is not self.status] + [(self.status, "就绪", "")]
        self.retranslate()
        if self.ball:
            self.ball.rebuild()

    def update_counts(self, *_):
        if hasattr(self, "out_count"):
            self.in_count.setText(tr("共 {n} 个文件").format(n=self.list.count()))
            self.out_count.setText(tr("共 {n} 个结果").format(n=self.results.count()))

    # ---- 托盘
    def make_tray(self):
        self.tray = QSystemTrayIcon(QIcon(os.path.join(ASSETS, "icon.ico")), self)
        self.tray.activated.connect(lambda r: self.show_main() if r in (
            QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray_menu = QMenu()
        self.tray.setContextMenu(self.tray_menu)
        self.tray.show()

    def build_tray_menu(self):
        if not hasattr(self, "tray"):
            return
        m = self.tray_menu
        m.clear()
        m.addAction(tr("打开主窗口"), self.show_main)
        m.addAction(tr("添加文件"), lambda: (self.show_main(), self.add_files()))
        m.addAction(tr("打开输出文件夹"), self.open_out)
        m.addSeparator()
        a = QAction(tr("显示悬浮球"), m, checkable=True)
        a.setChecked(bool(self.cfg.get("ball_on")))
        a.toggled.connect(self.set_ball)
        m.addAction(a)
        m.addAction(tr("悬浮球设置…"), self.open_ball_settings)
        m.addSeparator()
        m.addAction(tr("使用引导"), lambda: (self.show_main(), self.open_guide()))
        m.addAction(tr("帮助手册"), self.open_help)
        m.addSeparator()
        m.addAction(tr("退出"), self.quit_app)
        self.tray.setToolTip(f"{tr('格式转换器')} v{VERSION}")

    def set_ball(self, on):
        self.cfg["ball_on"] = on
        self.save()
        self.apply_ball()
        self.build_tray_menu()

    # ---- 引导 / 帮助
    def open_guide(self):
        Guide(self).exec()
        self.highlight(None)
        self.cfg["guided"] = True
        self.save()

    def open_help(self):
        HelpDialog(self).exec()

    # ---- 悬浮球
    assets = ASSETS
    tr = staticmethod(lambda s: tr(s))

    def save(self):
        save_cfg(self.cfg)

    def apply_ball(self):
        if self.cfg.get("ball_on"):
            if not self.ball:
                import floatball
                self.ball = floatball.FloatBall(self)
            self.ball.rebuild()
            self.ball.show()
        elif self.ball:
            self.ball.close()
            self.ball = None

    def open_ball_settings(self):
        dlg = BallSettings(self)
        if dlg.exec():
            self.cfg["ball_on"] = dlg.chk.isChecked()
            self.cfg["ball_formats"] = dlg.selected
            self.cfg["close_action"] = "hide" if dlg.rb_hide.isChecked() else "quit"
            self.save()
            self.apply_ball()
            self.build_tray_menu()

    def show_main(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        """完全退出：关掉悬浮窗与托盘，等转换线程结束，再退出事件循环。"""
        if self.ball:
            self.ball.close()
        self.tray.hide()
        for j in list(self.jobs) + ([self.worker] if getattr(self, "worker", None) else []):
            j.wait(3000)
        QApplication.instance().quit()

    def closeEvent(self, e):
        # 开着悬浮窗且设置为「隐藏」时，缩到系统托盘；否则完全退出
        if self.ball and self.cfg.get("close_action") == "hide":
            e.ignore()
            self.hide()
            if not self.cfg.get("tray_tip_shown"):
                self.tray.showMessage(tr("已最小化到系统托盘"), tr("格式转换器仍在后台运行，右键托盘图标可快速打开功能。"),
                                      QIcon(os.path.join(ASSETS, "icon.ico")), 4000)
                self.cfg["tray_tip_shown"] = True
                self.save()
        else:
            e.accept()
            self.quit_app()

    def run_job(self, files, fmt, kind, callback, auto_open=False):
        job = Worker(files, self.out_root, fmt, kind)
        self.jobs.append(job)

        def fin(ok, bad):
            self.jobs.remove(job)
            self.add_results(ok)
            if auto_open and ok:
                os.startfile(os.path.dirname(ok[0]))
            callback(ok, bad)
        job.finished_all.connect(fin)
        job.start()

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
            self.title.btn_max.setText("\ue923" if m else "\ue922")
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

    # ---- 输入文件
    def add_paths(self, paths):
        have = set(self.files())
        for p in paths:
            p = os.path.normpath(p)
            if os.path.isdir(p):
                for r, _, fs in os.walk(p):
                    self.add_paths([os.path.join(r, f) for f in fs])
                have = set(self.files())
            elif os.path.isfile(p) and p not in have:
                it = QListWidgetItem(self.icons.icon(QFileInfo(p)), f"{os.path.basename(p)}　　—　{os.path.dirname(p)}")
                it.setData(Qt.ItemDataRole.UserRole, p)
                it.setToolTip(p)
                self.list.addItem(it)
                have.add(p)

    def files(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def add_files(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("选择文件"))
        self.add_paths(fs)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("添加文件夹"))
        if d:
            self.add_paths([d])

    def remove_selected(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls()])

    # ---- 转换结果
    def add_results(self, paths):
        for p in paths:
            ext = os.path.splitext(p)[1][1:].lower()
            icon = self.icons.icon(QFileInfo(p))
            if ext in IMG_EXT:
                pm = QPixmap(p)
                if not pm.isNull():
                    icon = QIcon(pm.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
            it = QListWidgetItem(icon, os.path.basename(p))
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setToolTip(p)
            self.results.insertItem(0, it)
            it.setSelected(True)
        if paths:
            self.results.scrollToTop()

    def selected_results(self, need=True):
        ps = [it.data(Qt.ItemDataRole.UserRole) for it in self.results.selectedItems()]
        ps = [p for p in ps if os.path.exists(p)]
        if not ps and need:
            self.status.setText(tr("请先选择结果文件"))
        return ps

    def open_selected(self):
        for p in self.selected_results()[:20]:
            os.startfile(p)

    def results_menu(self, pos):
        if not self.results.itemAt(pos):
            return
        m = QMenu(self)
        m.addAction(tr("打开"), self.open_selected)
        m.addAction(tr("定位"), lambda: show_in_folder(self.selected_results()))
        m.addSeparator()
        for a in self.share_menu().actions():
            a.setParent(m)
            m.addAction(a)
        m.exec(self.results.mapToGlobal(pos))

    def share_menu(self):
        m = QMenu(self)
        m.addAction(tr("Windows 共享…"), self.share_windows)
        m.addAction(tr("复制文件（可粘贴到微信 / QQ / 邮件）"), self.share_copy)
        m.addAction(tr("复制文件路径"), self.share_paths)
        m.addAction(tr("打包为 ZIP 并定位"), lambda: self.share_zip(locate=True))
        return m

    def share_windows(self):
        ps = self.selected_results()
        if not ps:
            return
        if len(ps) > 1:
            p = self.share_zip(locate=False)
            self.status.setText(tr("多个文件已打包为 ZIP 再共享"))
        else:
            p = ps[0]
        windows_share(p)

    def share_copy(self):
        ps = self.selected_results()
        if ps:
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(p) for p in ps])
            QApplication.clipboard().setMimeData(md)
            self.status.setText(tr("已复制 {n} 个文件，可直接粘贴发送").format(n=len(ps)))

    def share_paths(self):
        ps = self.selected_results()
        if ps:
            QApplication.clipboard().setText("\n".join(ps))
            self.status.setText(tr("已复制路径"))

    def share_zip(self, locate=True):
        ps = self.selected_results()
        if not ps:
            return None
        base = os.path.join(os.path.dirname(ps[0]), time.strftime("分享_%H%M%S"))
        zp, i = base + ".zip", 1
        while os.path.exists(zp):
            i += 1
            zp = f"{base}_{i}.zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for p in ps:
                z.write(p, os.path.basename(p))
        self.status.setText(tr("已打包：{p}").format(p=zp))
        if locate:
            show_in_folder([zp])
        return zp

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
        self.results.clearSelection()
        self.add_results(ok)
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


class DlgTitle(QWidget):
    """对话框标题栏：图标 + 标题 + (可选语言按钮) + 关闭，可拖动。"""
    def __init__(self, dlg, lang_btn=False):
        super().__init__(objectName="title")
        self.dlg = dlg
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(QPixmap(os.path.join(ASSETS, "icon.png")).scaled(
            16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(ic)
        self.text = QLabel(objectName="titleText")
        lay.addWidget(self.text)
        lay.addStretch()
        self.btn_lang = None
        if lang_btn:
            self.btn_lang = QPushButton(objectName="lang")
            self.btn_lang.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lay.addWidget(self.btn_lang)
        self.btn_close = QPushButton("", objectName="close")
        self.btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_close.clicked.connect(dlg.reject)
        lay.addWidget(self.btn_close)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.dlg.windowHandle().startSystemMove()


class StyledDialog(QDialog):
    """与主窗口同风格的无边框对话框；内容放进 self.content。"""
    def __init__(self, parent, title_key, lang_btn=False, accent=False):
        super().__init__(parent)
        self.title_key = title_key
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(BORDER, BORDER, BORDER, BORDER)
        self.frame = QFrame(objectName="frame")
        if accent:
            self.frame.setStyleSheet("#frame{border:1px solid #0a84ff}")
        outer.addWidget(self.frame)
        fl = QVBoxLayout(self.frame)
        fl.setContentsMargins(1, 1, 1, 1)
        fl.setSpacing(0)
        self.titlebar = DlgTitle(self, lang_btn)
        fl.addWidget(self.titlebar)
        body = QWidget()
        fl.addWidget(body, 1)
        self.content = QVBoxLayout(body)
        self.content.setContentsMargins(16, 6, 16, 14)
        self.retitle()

    def retitle(self):
        self.setWindowTitle(tr(self.title_key))
        self.titlebar.text.setText(tr(self.title_key))
        if self.titlebar.btn_lang:
            self.titlebar.btn_lang.setText("EN" if LANG == "zh" else "中文")
            self.titlebar.btn_lang.setToolTip(tr("切换语言"))


class HelpDialog(StyledDialog):
    def __init__(self, main):
        super().__init__(main, "帮助手册")
        self.resize(680, 640)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setHtml("<style>h2{color:#4ea1ff} h3{color:#fff;margin-top:14px} li{margin:3px 0} code{color:#e3b341}</style>"
                   + (HELP_EN if LANG == "en" else HELP_ZH))
        self.content.addWidget(tb)
        h = QHBoxLayout()
        h.addStretch()
        ok = QPushButton(tr("确定"), objectName="primary")
        ok.clicked.connect(self.accept)
        h.addWidget(ok)
        self.content.addLayout(h)


class Guide(StyledDialog):
    """新手引导：逐步介绍各模块，并高亮对应模块框；可切换语言，与主程序同步。"""
    def __init__(self, main):
        super().__init__(main, "使用引导", lang_btn=True, accent=True)
        self.main = main
        self.i = 0
        self.setFixedWidth(430)
        self.titlebar.btn_lang.clicked.connect(self.switch_lang)
        v = self.content
        v.setContentsMargins(22, 8, 22, 16)
        self.head = QLabel(objectName="cardTitle")
        self.head.setStyleSheet("font-size:17px")
        self.body = QLabel(wordWrap=True)
        self.body.setStyleSheet("color:#cfcfcf;line-height:150%")
        self.body.setMinimumHeight(80)
        self.dots = QLabel(objectName="hint")
        v.addWidget(self.head)
        v.addWidget(self.body)
        h = QHBoxLayout()
        h.addWidget(self.dots)
        h.addStretch()
        self.b_skip = QPushButton()
        self.b_back = QPushButton()
        self.b_next = QPushButton(objectName="primary")
        self.b_skip.clicked.connect(self.reject)
        self.b_back.clicked.connect(lambda: self.go(-1))
        self.b_next.clicked.connect(lambda: self.go(1))
        for b in (self.b_skip, self.b_back, self.b_next):
            h.addWidget(b)
        v.addLayout(h)
        self.go(0)

    def switch_lang(self):
        self.main.toggle_lang()   # 主窗口、托盘、悬浮球同步切换
        self.retitle()
        self.go(0)

    def go(self, d):
        self.i += d
        self.steps = GUIDE["en" if LANG == "en" else "zh"]
        if self.i >= len(self.steps):
            self.accept()
            return
        self.b_skip.setText(tr("跳过"))
        self.b_back.setText(tr("上一步"))
        title, text, card = self.steps[self.i]
        self.head.setText(title)
        self.body.setText(text)
        self.dots.setText("  ".join("●" if k == self.i else "○" for k in range(len(self.steps))))
        self.b_back.setEnabled(self.i > 0)
        self.b_next.setText(tr("开始使用") if self.i == len(self.steps) - 1 else tr("下一步"))
        self.main.highlight(card)
        self.adjustSize()
        # 放在被介绍的模块旁边，没有对应模块时居中
        mg = self.main.geometry()
        target = {"in": self.main.card_in, "fmt": self.main.card_fmt, "out": self.main.card_out}.get(card)
        if target:
            c = target.mapToGlobal(target.rect().center())
            x = min(max(c.x() - self.width() // 2, mg.left()), mg.right() - self.width())
            y = min(max(c.y() - self.height() // 2, mg.top()), mg.bottom() - self.height())
            self.move(x, y)
        else:
            self.move(mg.center() - self.rect().center())


class BallSettings(StyledDialog):
    """悬浮球设置：开关 + 最多 6 种常用格式。"""
    MAX = 6

    def __init__(self, main):
        super().__init__(main, "悬浮球设置")
        self.setStyleSheet("QCheckBox, QRadioButton{color:#e6e6e6}"
                           "QPushButton#fmt:checked{background:#0a84ff;border-color:#0a84ff;color:white}")
        self.selected = list(main.cfg.get("ball_formats", []))[:self.MAX]
        lay = self.content
        self.chk = QCheckBox(tr("在屏幕边缘显示悬浮球"))
        self.chk.setChecked(bool(main.cfg.get("ball_on")))
        lay.addWidget(self.chk)
        crow = QHBoxLayout()
        crow.addWidget(QLabel(tr("关闭主窗口时：")))
        self.rb_quit = QRadioButton(tr("完全退出"))
        self.rb_hide = QRadioButton(tr("隐藏到系统托盘，保留悬浮球"))
        (self.rb_hide if main.cfg.get("close_action") == "hide" else self.rb_quit).setChecked(True)
        crow.addWidget(self.rb_quit)
        crow.addWidget(self.rb_hide)
        crow.addStretch()
        lay.addLayout(crow)
        self.chk.toggled.connect(self.rb_hide.setEnabled)
        self.rb_hide.setEnabled(self.chk.isChecked())
        self.count = QLabel()
        self.count.setStyleSheet("color:#999")
        lay.addWidget(self.count)
        self.btns = []
        for name, kind, fmts in (("图像", "image", converter.IMAGE_FORMATS), ("文档", "doc", converter.DOC_FORMATS),
                                 ("表格", "sheet", converter.SHEET_FORMATS), ("向量", "vector", converter.VECTOR_FORMATS)):
            lay.addWidget(QLabel(tr(name)))
            g = QGridLayout()
            g.setSpacing(6)
            for k, f in enumerate(fmts):
                b = QPushButton(f, objectName="fmt", checkable=True)
                b.setMinimumWidth(64)
                key = f"{kind}:{f}"
                b.setChecked(key in self.selected)
                b.toggled.connect(lambda on, key=key, b=b: self.toggle(key, on, b))
                g.addWidget(b, k // 8, k % 8)
                self.btns.append(b)
            lay.addLayout(g)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Ok).setText(tr("确定"))
        box.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消"))
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.refresh()

    def toggle(self, key, on, b):
        if on and key not in self.selected:
            if len(self.selected) >= self.MAX:
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
                return
            self.selected.append(key)
        elif not on and key in self.selected:
            self.selected.remove(key)
        self.refresh()

    def refresh(self):
        self.count.setText(tr("选择常用格式（最多 6 种）：已选 {n}/6").format(n=len(self.selected))
                           + ("　" + "  ".join(k.split(":")[1] for k in self.selected) if self.selected else ""))


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
    app.setQuitOnLastWindowClosed(False)
    w.show()
    w.apply_ball()
    if not w.cfg.get("guided"):
        QTimer.singleShot(400, w.open_guide)
    code = app.exec()
    os._exit(code)  # 直接结束进程，避免后台库线程拖住退出
