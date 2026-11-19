"""格式转换器 —— 拖入任意文件，点格式按钮即转换。输出到「输出根目录\\日期」文件夹。"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import zipfile

from PyQt6.QtCore import QEasingCurve, QByteArray, Qt, QThread, pyqtSignal, pyqtProperty, QPropertyAnimation, QUrl, QPoint, QTimer, QMimeData, QFileInfo, QSize, QRectF, QPointF
from PyQt6.QtGui import QFont, QCursor, QImageReader, QBrush, QPainter, QPen, QColor, QDesktopServices, QIcon, QPixmap, QKeySequence, QShortcut, QAction
from PyQt6.QtWidgets import (QSizePolicy, QApplication, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QStackedWidget, QVBoxLayout, QWidget, QProgressBar, QFrame,
                             QCheckBox, QRadioButton, QSystemTrayIcon, QMenu,
                             QFileIconProvider, QAbstractItemView, QTextBrowser,
                             QScrollArea, QSpinBox, QComboBox, QTreeWidget, QTreeWidgetItem, QLineEdit,
                             QHeaderView)

import converter
import videoconv
import safejob

SEC_DEFAULTS = {"ask_on_fail": True, "share_confirm": True, "strip_meta": True, "clean_temp": True, "isolate": True,
                "timeout_s": 300, "mem_mb": 4096, "max_mb": 500, "max_mpix": 200, "max_unzip_mb": 2048,
                "auto_delete_days": 0, "history_days": 30}
HISTORY_DAYS = (7, 30, 90, 180, 365)
LEVEL_TEXT = {"full": "完整转换", "partial": "部分输出", "preview": "仅生成预览", "failed": "失败",
              "cancelled": "已取消", "pending": "等待中", "running": "转换中"}
LEVEL_COLOR = {"full": "#e6e6e6", "partial": "#e3b341", "preview": "#f0883e", "failed": "#ff7b72", "cancelled": "#8d8d8d"}
META_TEXT = {"clean": "元数据已清理", "partial": "元数据部分清理", "unsupported": "此格式不支持清理元数据",
             "kept": "元数据未清理（设置已关闭）"}
CAPS = {
    "image": "每页 / 每帧输出一张图片（文档最多 200 页，动图最多 100 帧）；视频转 GIF / WEBP 生成动图（每秒 10 帧，最多 10 秒）；文字变为图像，不可再编辑。",
    "doc": "提取文字、表格与图片后重新排版，原字体、版式与图片位置不保留；PDF 最多 200 页；DJVU 需 DjVuLibre。",
    "sheet": "导出表格：Excel 工作表、PDF / Word 中识别到的表格；公式按计算结果导出，样式与图表不保留。",
    "vector": "PDF / AI 转 SVG、AI 为真矢量；其他来源以图像嵌入或像素描摹。",
    "video": "视频重新编码或只换封装：可选 H.264 / H.265 / AV1 / VP9 / VP8 / ProRes / DNxHR / MPEG-2 / MJPEG；所选编码与格式不兼容时自动改用推荐编码；只保留第 1 条音轨，字幕不保留。",
    "preset": "使用保存的格式与参数（质量、最长边、页码）转换，主窗口与悬浮球共用。",
}
CAPS_COMMON = "无法识别的文件只生成信息预览；视频转 GIF / WEBP 为动图，转视频类格式为完整转码，转其他格式只取一帧，音频只生成文件信息；结果会标注「完整转换」「部分输出」「仅生成预览」或「失败」。"
SYNC_ENV = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")

VERSION = "1.13.3"
HERE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
ASSETS = os.path.join(getattr(sys, "_MEIPASS", HERE), "assets")
CONFIG = os.path.join(os.environ.get("APPDATA", HERE), "格式转换器", "config.json")
DEFAULT_OUT = os.path.join(os.path.expanduser("~"), "格式转换输出")
FALLBACK_OUT = os.path.join(os.path.expanduser("~"), "Downloads", "格式转换输出")
BORDER = 6  # 窗口四周可拖拽缩放的宽度
IMG_EXT = {"png", "jpg", "jpeg", "bmp", "gif", "webp", "ico", "tif", "tiff"}

THEMES = {
    "dark": dict(frame="#17171a", border="#2c2c31", text="#e4e4e7", muted="#a1a1aa", faint="#71717a",
                 card="#1e1e22", cardb="#2a2a30", nav="#141417", area="#25252a", areab="#303037",
                 btn="#2b2b31", btnh="#35353c", btnb="#3a3a42", inp="#202024", list="#19191c", listb="#3a3a42",
                 accent="#3b82f6", accenth="#5b9bff", soft="#1f2c47", softt="#9cc2ff", sel="#24365a",
                 sep="#303036", warn="#e3b341", tbh="#2a2a2f", tbp="#33333a", knob_off="#4a4a52", hl="#3b82f6"),
    "light": dict(frame="#e9ebef", border="#d3d7de", text="#2b2f36", muted="#5c6370", faint="#8a909b",
                  card="#f3f4f7", cardb="#dcdfe5", nav="#e3e6eb", area="#eceef2", areab="#d8dce3",
                  btn="#f8f9fb", btnh="#eef0f4", btnb="#cfd4dc", inp="#f8f9fb", list="#eef0f3", listb="#c9ced7",
                  accent="#3a73d6", accenth="#4c84e6", soft="#d6e2f7", softt="#2256b5", sel="#cddcf6",
                  sep="#d0d4db", warn="#a86f00", tbh="#dde0e6", tbp="#d2d6dd", knob_off="#b9bfc9", hl="#3a73d6"),
}
THEME = "dark"
BASE_THEMES = {k: dict(v) for k, v in THEMES.items()}
# 颜色预设：背景色调（混入少量色相）与按键高光色
BG_PRESETS = (("default", "默认", None), ("graphite", "石墨", "#8a8f98"), ("ocean", "深海", "#3b6fd6"),
              ("forest", "森林", "#2f9e6e"), ("sand", "暖沙", "#c08a4a"), ("dusk", "暮紫", "#7c5cd6"),
              ("rose", "玫瑰", "#d0587e"))
ACCENT_PRESETS = (("blue", "蓝", "#3b82f6"), ("violet", "紫", "#8b5cf6"), ("teal", "青", "#14b8a6"),
                  ("green", "绿", "#22a06b"), ("orange", "橙", "#f97316"), ("pink", "粉", "#ec4899"),
                  ("red", "红", "#ef4444"))
PALETTE = {"bg": "default", "accent": "blue"}


def _mix(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t)).name()


def compose_palette(bg=None, accent=None):
    """按预设重新生成深色 / 浅色两套配色。"""
    PALETTE["bg"] = bg or PALETTE["bg"]
    PALETTE["accent"] = accent or PALETTE["accent"]
    tint = dict((k, c) for k, _, c in BG_PRESETS).get(PALETTE["bg"])
    acc = dict((k, c) for k, _, c in ACCENT_PRESETS).get(PALETTE["accent"], "#3b82f6")
    for mode, base in BASE_THEMES.items():
        t = dict(base)
        dark = mode == "dark"
        if tint:
            for k in ("frame", "card", "nav", "area", "btn", "btnh", "inp", "list", "tbh", "tbp",
                      "cardb", "border", "areab", "btnb", "listb", "sep"):
                t[k] = _mix(base[k], tint, 0.09 if dark else 0.10)
        if PALETTE["accent"] != "blue":
            a = acc if dark else _mix(acc, "#000000", 0.08)
            t.update(accent=a, hl=a, accenth=_mix(a, "#ffffff", 0.2 if dark else 0.12),
                     soft=_mix(t["card"], a, 0.22 if dark else 0.18),
                     softt=_mix(a, "#ffffff", 0.45) if dark else _mix(a, "#000000", 0.3),
                     sel=_mix(t["card"], a, 0.3 if dark else 0.25))
        THEMES[mode] = t

QSS_TEMPLATE = """
#frame { background:@frame; border:1px solid @border; border-radius:10px; }
#frame[max="true"] { border:none; border-radius:0; }
QWidget { color:@text; font-family:"Microsoft YaHei UI"; font-size:13px; }
QLabel { background:transparent; }
QCheckBox, QRadioButton { color:@text; spacing:8px; }
QCheckBox::indicator, QRadioButton::indicator { width:16px; height:16px; border:1px solid @btnb; background:@inp; }
QCheckBox::indicator { border-radius:4px; } QRadioButton::indicator { border-radius:8px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color:@accent; }
QCheckBox::indicator:checked { background:@accent; border-color:@accent; image:url(@check); }
QRadioButton::indicator:checked { background:@accent; border-color:@accent; image:url(@dot); }
QSpinBox:hover, QComboBox:hover, QLineEdit:hover { border-color:@accent; }
#title { background:transparent; }
#titleText { font-size:13px; font-weight:bold; color:@text; }
#version { font-size:11px; color:@faint; }
#title QPushButton { background:transparent; border:1px solid @btnb; border-radius:6px; min-width:30px; max-width:30px;
                     min-height:26px; max-height:26px; padding:0; color:@muted;
                     font-family:"Segoe Fluent Icons","Segoe MDL2 Assets"; font-size:10px; }
#title QPushButton:hover { background:@btnh; color:@text; border-color:@accent; }
#title QPushButton:pressed { background:@tbp; }
#title QPushButton#lang { font-family:"Microsoft YaHei UI"; font-size:11px; font-weight:bold;
                          min-width:34px; max-width:34px; }
#title QPushButton#help { font-size:13px; }
#title QPushButton#close:hover { background:#e5484d; color:white; border-color:#e5484d; }
#themeIcon { color:@muted; font-family:"Segoe Fluent Icons","Segoe MDL2 Assets"; font-size:12px; }
#titleSep { background:@sep; min-width:1px; max-width:1px; min-height:16px; max-height:16px; }
#side { background:@nav; border-right:1px solid @cardb; border-radius:0; border-bottom-left-radius:10px; }
#side[hl="true"] { border:2px solid @hl; border-radius:10px; }
#sideSep { background:@sep; margin:2px 6px; }
QPushButton#sideBtn { background:transparent; border:1px solid transparent; border-radius:8px; padding:0; text-align:left; }
QPushButton#sideBtn:hover { background:@btnh; border-color:@btnb; }
QPushButton#sideBtn:checked { background:@soft; border-color:@accent; }
QPushButton#tool { background:@btn; border:1px solid @btnb; padding:5px 14px; border-radius:8px; color:@text; }
QPushButton#tool:hover { background:@btnh; border-color:@accent; }
#card { background:@card; border:1px solid @cardb; border-radius:12px; }
#card[hl="true"] { border:2px solid @hl; }
#cardTitle { font-size:14px; font-weight:bold; color:@text; }
#hint { color:@faint; font-size:12px; }
#capHint { color:@muted; font-size:12px; }
#section { color:@muted; font-size:12px; font-weight:bold; padding-top:6px; }
#pill { background:@soft; color:@softt; border-radius:10px; padding:3px 10px; font-size:12px; }
#box { background:@area; border:1px solid @areab; border-radius:8px; padding:8px; }
#cats, #navPanel { background:@nav; border:1px solid @cardb; border-radius:10px; }
#cats QPushButton { text-align:left; padding:6px 12px; min-height:22px; border:1px solid @cardb; border-radius:7px;
                    color:@muted; background:@btn; }
#cats QPushButton:hover { background:@btnh; color:@text; border-color:@accent; }
#cats QPushButton:checked { color:@softt; font-weight:bold; background:@soft; border:1px solid @accent;
                            border-left:3px solid @accent; }
#cats QPushButton#navBtn { padding:0 12px; min-height:29px; font-size:14px; }
#fmtArea, #panel { background:@area; border:1px solid @areab; border-radius:10px; }
QPushButton#fmt { background:@btn; border:1px solid @btnb; border-radius:8px; min-width:56px; padding:0 6px;
                  min-height:32px; font-weight:bold; }
QPushButton#fmt:hover { background:@btnh; border-color:@accent; }
QPushButton#fmt:pressed { background:@accent; color:white; }
QPushButton#fmt:disabled { color:@faint; }
QPushButton#fmt:checked { background:@accent; border-color:@accent; color:white; }
QPushButton#go { background:@accent; border:1px solid @accent; color:white; font-weight:bold; min-height:34px;
                 min-width:150px; border-radius:8px; padding:4px 16px; }
QPushButton#go:hover { background:@accenth; }
QPushButton#go:disabled { background:@btn; color:@faint; border-color:@btnb; }
QProgressBar#mini { border:none; background:@btnb; max-height:6px; min-height:6px; border-radius:3px; }
QProgressBar#mini::chunk { background:@accent; border-radius:3px; }
QPushButton { background:@btn; border:1px solid @btnb; border-radius:8px; padding:5px 12px; color:@text; }
QPushButton:hover { background:@btnh; border-color:@accent; }
QPushButton:pressed { background:@tbp; }
QPushButton:disabled { color:@faint; }
QPushButton#primary { background:@accent; border-color:@accent; color:white; }
QPushButton#primary:hover { background:@accenth; border-color:@accenth; }
QPushButton#primary:pressed, QPushButton#go:pressed { background:@accent; padding-top:6px; }
QListWidget { background:@list; border:1px dashed @listb; border-radius:10px; outline:none; }
QListWidget#results, QListWidget#plain { border:1px solid @cardb; }
QListWidget::item { padding:6px 8px; border-radius:6px; }
QListWidget::item:selected { background:@sel; color:@text; }
QListWidget::item:hover { background:@btnh; }
QProgressBar { border:none; background:@btnb; max-height:6px; border-radius:3px; }
QProgressBar::chunk { background:@accent; border-radius:3px; }
QScrollBar:vertical { background:transparent; width:8px; }
QScrollBar::handle:vertical { background:@btnb; border-radius:4px; min-height:24px; }
QScrollBar::add-line, QScrollBar::sub-line { height:0; }
QMenu { background:@card; color:@text; border:1px solid @cardb; border-radius:8px; padding:4px; }
QMenu::item { padding:6px 22px; border-radius:6px; } QMenu::item:selected { background:@accent; color:white; }
QMenu::separator { height:1px; background:@sep; margin:4px 8px; }
QToolTip { background:@card; color:@text; border:1px solid @cardb; border-radius:6px; padding:4px 6px; }
QDialog { background:@frame; }
QSpinBox, QComboBox, QLineEdit { background:@inp; border:1px solid @btnb; border-radius:8px; padding:4px 8px;
                                 min-width:90px; min-height:20px; color:@text; }
QSpinBox:focus, QComboBox:focus, QLineEdit:focus { border-color:@accent; }
QSpinBox:disabled, QComboBox:disabled, QLineEdit:disabled { color:@faint; background:@area; }
QComboBox { padding-right:26px; }
QComboBox::drop-down { subcontrol-origin:padding; subcontrol-position:center right; width:24px; border:none;
                       border-top-right-radius:8px; border-bottom-right-radius:8px; }
QComboBox::down-arrow { image:url(@arrow_down); width:10px; height:10px; }
QComboBox::down-arrow:on { image:url(@arrow_up); }
QComboBox::down-arrow:disabled { image:url(@arrow_down_off); }
QSpinBox { padding-right:24px; }
QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin:border; width:22px; border:none; background:transparent; }
QSpinBox::up-button { subcontrol-position:top right; margin:3px 3px 0 0; border-top-right-radius:6px; }
QSpinBox::down-button { subcontrol-position:bottom right; margin:0 3px 3px 0; border-bottom-right-radius:6px; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover, QComboBox::drop-down:hover { background:@btnh; }
QSpinBox::up-arrow { image:url(@arrow_up); width:8px; height:8px; }
QSpinBox::down-arrow { image:url(@arrow_down); width:8px; height:8px; }
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled { image:url(@arrow_down_off); }
QComboBox QAbstractItemView { background:@card; border:1px solid @cardb; selection-background-color:@accent;
                              selection-color:white; outline:none; }
QScrollArea { background:transparent; border:none; }
QAbstractScrollArea > QWidget#qt_scrollarea_viewport, QScrollArea > QWidget > QWidget { background:transparent; }
QStackedWidget, #pageBody, QScrollArea > QWidget#qt_scrollarea_viewport > QWidget { background:transparent; }
QScrollBar:vertical { margin:4px 2px 4px 0; border-radius:4px; }
QScrollBar:horizontal { background:transparent; height:8px; margin:0 4px 2px 4px; border-radius:4px; }
QScrollBar::handle:horizontal { background:@btnb; border-radius:4px; min-width:24px; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
QHeaderView { background:transparent; border:none; }
QHeaderView::section:first { border-top-left-radius:8px; }
QHeaderView::section:last { border-top-right-radius:8px; }
QTreeWidget { font-size:14px; outline:none; show-decoration-selected:1; }
QTreeWidget::item { border:none; border-radius:0; padding:6px 0; }
QTreeWidget::item:hover { background:@btnh; }
QTreeWidget::item:selected { background:@sel; color:@text; border-radius:0; }
QTreeWidget::branch:selected { background:@sel; }
QTreeWidget::branch:hover { background:@btnh; }
QHeaderView::section { font-size:13px; padding:6px 4px; }
QListWidget { font-size:14px; }
#navName { font-size:14px; color:@muted; background:transparent; }
#navCount { font-size:11px; color:@faint; background:@area; border-radius:9px; padding:1px 8px; }
#datePill { background:@area; color:@text; border:1px solid @areab; border-radius:11px; padding:3px 12px;
            font-weight:bold; font-size:12px; }
#tlTime { color:@muted; font-size:12px; }
#tlCard { background:@card; border:1px solid @cardb; border-radius:10px; }
#tlCard:hover { border-color:@accent; }
#tlTitle { font-weight:bold; font-size:14px; color:@text; }
#tlSub { color:@muted; font-size:12px; }
QComboBox QAbstractItemView { border-radius:8px; padding:4px; }
QComboBox QAbstractItemView::item { border-radius:6px; padding:5px 8px; min-height:20px; }
QTextBrowser, QListWidget, QTreeWidget { padding:2px; }
#warn { color:@warn; font-size:12px; }
#pageBody { background:transparent; }
#pageHead { background:transparent; }
#pageTitle { font-size:15px; font-weight:bold; color:@text; }
#pageSep { background:@sep; }
#pageCard { background:@card; border:2px solid @accent; border-radius:12px; }
QPushButton#back { background:@soft; border:1px solid @accent; border-radius:8px; padding:5px 14px;
                   color:@softt; font-weight:bold; }
QPushButton#back:hover { background:@accent; color:white; border-color:@accent; }
QPushButton#back:pressed { background:@accenth; color:white; }
QTextBrowser { background:@list; border:1px solid @cardb; border-radius:8px; }
QTreeWidget { background:@list; border:1px solid @cardb; border-radius:8px; }
QHeaderView::section { background:@area; color:@muted; border:none; padding:4px; }
"""


def _arrows(theme):
    """按主题颜色生成细线箭头 SVG，供下拉框 / 数字框使用。"""
    t = THEMES[theme]
    d = os.path.join(os.environ.get("TEMP", HERE), "FormatConverter_ui")
    os.makedirs(d, exist_ok=True)
    out = {}
    for name, pts, col in (("arrow_down", "2,4.5 6,8.5 10,4.5", t["muted"]), ("arrow_up", "2,7.5 6,3.5 10,7.5", t["muted"]),
                           ("arrow_down_off", "2,4.5 6,8.5 10,4.5", t["faint"]), ("check", "2.5,6.2 5,8.6 9.5,3.6", "#ffffff"), ("dot", None, "#ffffff")):
        path = os.path.join(d, f"{name}_{theme}.svg")
        with open(path, "w", encoding="utf-8") as f:
            shape = (f'<circle cx="6" cy="6" r="2.6" fill="{col}"/>' if pts is None else
                     f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.6" '
                     f'stroke-linecap="round" stroke-linejoin="round"/>')
            f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">{shape}</svg>')
        out[name] = path.replace("\\", "/")
    return out


def build_qss(theme):
    t = dict(THEMES[theme])
    t.update(_arrows(theme))
    s = QSS_TEMPLATE
    for k in sorted(t, key=len, reverse=True):
        s = s.replace("@" + k, t[k])
    return s


def C(key):
    return THEMES[THEME][key]


QSS = build_qss("dark")


LANG = "zh"
EN = {
    "格式转换器": "Format Converter",
    "添加文件": "Add files", "添加文件夹": "Add folder", "清空": "Clear", "移除所选": "Remove",
    "更改输出目录…": "Change output…", "打开输出文件夹": "Open output folder",
    "图像": "Image", "文档": "Document", "表格": "Spreadsheet", "向量": "Vector", "视频": "Video",
    "视频编码": "Video codec", "视频编码（仅视频）": "Video codec (video only)",
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
    "移除": "Remove",
    "完整转换": "Complete", "部分输出": "Partial output", "仅生成预览": "Preview only", "失败": "Failed",
    "等待中": "Waiting", "转换中": "Converting", "已完成": "Done",
    "元数据已清理": "Metadata removed", "元数据部分清理": "Metadata partly removed",
    "此格式不支持清理元数据": "Metadata cleaning not supported for this format",
    "元数据未清理（设置已关闭）": "Metadata kept (setting is off)",
    "不是本次生成的结果，元数据状态未知": "Not produced in this session; metadata status unknown",
    "{n} 个文件需要人工检查（见 ⚠ 标记）。": "{n} file(s) need a manual check (marked ⚠). ",
    "每页 / 每帧输出一张图片（文档最多 200 页，动图最多 100 帧）；视频转 GIF / WEBP 生成动图（每秒 10 帧，最多 10 秒）；文字变为图像，不可再编辑。":
        "One image per page / frame (documents up to 200 pages, animations up to 100 frames); video to GIF / WEBP makes an animation (10 fps, up to 10 s); text becomes pixels.",
    "提取文字、表格与图片后重新排版，原字体、版式与图片位置不保留；PDF 最多 200 页；DJVU 需 DjVuLibre。":
        "Text, tables and images are extracted and re-laid out; original fonts, layout and image positions are lost; PDF up to 200 pages; DJVU needs DjVuLibre.",
    "导出表格：Excel 工作表、PDF / Word 中识别到的表格；公式按计算结果导出，样式与图表不保留。":
        "Exports tables: Excel sheets and tables found in PDF / Word; formulas become values, styles and charts are dropped.",
    "PDF / AI 转 SVG、AI 为真矢量；其他来源以图像嵌入或像素描摹。":
        "PDF / AI to SVG or AI is true vector; other sources are embedded as images or traced from pixels.",
    "使用保存的格式与参数（质量、最长边、页码）转换，主窗口与悬浮球共用。":
        "Converts with saved format and parameters (quality, longest side, pages); shared by the main window and floating ball.",
    "无法识别的文件只生成信息预览；视频转 GIF / WEBP 为动图，转其他格式只取一帧，音频只生成文件信息；结果会标注「完整转换」「部分输出」「仅生成预览」或「失败」。":
        "Unknown files only get an info preview; video to GIF / WEBP is animated, other formats get one frame, audio gives file info. Results are labelled Complete, Partial output, Preview only or Failed.",
    "按预设只处理第 {p} 页": "Preset: pages {p} only",
    "提取文字与表格重新排版，原字体、版式与页面图片不保留": "Text and tables re-laid out; original fonts, layout and page images are lost",
    "保留文字、表格与图片，原排版样式不保留": "Text, tables and images kept; original styling lost",
    "文字重新排版后渲染为图片，原排版样式不保留": "Text re-laid out and rendered as images; original styling lost",
    "文字渲染为图片，不再是可编辑文字": "Text rendered as images, no longer editable",
    "没有识别到表格，文字放在「文本」工作表中": "No tables found; text placed in a “文本” sheet",
    "以图像嵌入或像素描摹生成，不是真矢量": "Embedded as an image or traced from pixels; not true vector",
    "图片嵌入文档，不做文字识别": "Images embedded; no OCR",
    "公式按计算后的值导出，单元格样式与图表不保留": "Formulas exported as values; cell styles and charts dropped",
    "视频只提取一帧画面": "Only one video frame extracted", "音频只生成文件信息": "Audio: file info only",
    "已按「移除敏感元数据」设置略去音频标签": "Audio tags omitted (remove metadata is on)",
    "无法识别文件内容，只生成文件信息与十六进制预览": "Unknown content; file info and hex preview only",
    "文本超过 8 MB，只处理前 8 MB": "Text over 8 MB; only the first 8 MB processed",
    "按每秒 10 帧生成动图，不含音频": "Animated at 10 fps, no audio",
    "转换预设…": "Presets…", "预设": "Presets", "返回": "Back", "历史": "History", "历史记录": "History", "历史记录保留时间": "Keep history for",
    "{d} 天": "{d} days", "「历史」页只显示这段时间内的转换记录，更早的记录会被清除（只删记录，不删文件）。":
    "History shows conversions in this period; older records are removed (files are not deleted).",
    "最近 {d} 天的转换记录（可在「设置 → 安全」修改）": "Conversions from the last {d} days (change in Settings → Security)",
    "搜索文件名": "Search file name", "暂无转换记录": "No conversions yet", "已删除": "Deleted",
    "周一": "Mon", "周二": "Tue", "周三": "Wed", "周四": "Thu", "周五": "Fri", "周六": "Sat", "周日": "Sun",
    "主窗口": "Main window", "悬浮球": "Floating ball", "资源与清理": "Resources & cleanup",
    "先选择目标格式，再点「开始转换」，避免点错格式直接生成": "Pick a target format, then click “Start” — no accidental conversions",
    "开始转换": "Start", "请先选择格式": "Pick a format first", "转换中…": "Converting…",
    "选中结果时在文件夹中定位；未选中时打开输出文件夹：": "Shows the selected result in its folder; with nothing selected, opens the output folder:",
    "悬浮球转换完成后自动打开输出文件夹": "Open the output folder automatically after floating-ball conversions",
    "正在转换 {n} 个": "Converting {n}", "下一批 {n} 个": "next batch {n}", "完成 {n} 个": "{n} done",
    "取消任务": "Cancel task", "打开输出": "Open output", "查看失败": "View failures", "重试失败项": "Retry failed",
    "还有 {n} 个 ▸": "{n} more ▸", "收起 ▴": "Collapse ▴", "正在扫描文件夹…": "Scanning folders…",
    "已找到 {n} 个文件": "{n} file(s) found", "松开以添加文件": "Release to add files",
    "转换中 {a}/{b}": "{a}/{b}", "锁定位置": "Lock position", "重置位置": "Reset position", "查看任务": "Tasks",
    "下一批将在当前任务完成后选择格式": "Choose a format for the next batch after this task finishes",
    "点击展开": "Click to expand", "失败 {n}": "{n} failed", "上一批：": "Last batch: ", "关闭结果": "Close result", "预设": "Presets", "管理预设…": "Manage presets…", "任务": "Tasks",
    "质量 {q}%": "quality {q}%", "最长边 {n}px": "longest side {n}px", "第 {p} 页": "pages {p}",
    "主窗口": "Main window", "重试": "Retry",
    "资源限制未生效": "Resource limits not applied",
    "处理进程的内存 / 优先级限制没有成功应用：": "Memory / priority limits for the worker process were not applied: ",
    "任务 / 文件": "Task / file", "状态": "Status", "说明": "Details",
    "取消任务": "Cancel task", "重试失败项": "Retry failed", "清除已结束": "Clear finished", "进行中 {n} 个": "{n} running",
    "转换预设": "Conversion presets", "默认": "Default", "不缩放": "No resize", "例如 1-3,5；留空为全部": "e.g. 1-3,5; empty = all",
    "名称": "Name", "基本": "Basics", "参数": "Options", "质量": "Quality", "最长边": "Longest side", "类别": "Category", "格式": "Format", "质量（JPEG/WEBP/AVIF/HEIC）": "Quality (JPEG/WEBP/AVIF/HEIC)",
    "最长边（像素，仅图像）": "Longest side (px, images only)", "最长边（像素，图像 / 视频）": "Longest side (px, image / video)",
    "自动（按格式推荐）": "Auto (recommended for format)", "H.264 / AVC（通用）": "H.264 / AVC (universal)",
    "保持原编码（只换封装，最快）": "Keep original codec (remux only, fastest)", "页码 / 帧": "Pages / frames",
    "新建": "New", "删除": "Delete", "保存": "Save", "新预设": "Preset",
    "「{n}」的页码格式不正确，例如 1-3,5": "Invalid pages for “{n}”, e.g. 1-3,5",
    "{n} 个超过 {d} 天的生成文件已移到回收站": "{n} generated file(s) older than {d} days moved to the Recycle Bin",
    "定时删除只处理本程序生成并记录在清单中的文件；你放进去的文件或生成后被修改过的文件不会删除。到期文件移到回收站，可以还原。":
        "Auto-delete only touches files this app generated and recorded; your own files and generated files you modified are never removed. Expired files go to the Recycle Bin.",
    "以下 {n} 个由本程序生成的文件已超过 {d} 天，确定后会移到回收站：": "These {n} generated file(s) are older than {d} days and will be moved to the Recycle Bin:",
    "目前没有到期的文件。清单中共记录 {t} 个生成文件，之后只会清理其中超过 {d} 天且未被修改的项目。":
        "Nothing has expired yet. {t} generated file(s) are recorded; only those older than {d} days and unmodified will be cleaned.",
    "你自己放进输出目录的文件、以及生成后被修改过的文件都不会被删除。": "Files you put in the output folder yourself, and generated files you modified, are never deleted.", "输出目录无法写入": "Output folder is not writable", "本次已改存到：": "Saved this time to: ",
    "已清理过期的生成文件": "Old output cleaned up", "{n} 个超过 {d} 天的日期文件夹已移到回收站": "{n} dated folder(s) older than {d} days moved to the Recycle Bin",
    "⚠ 输出目录位于云同步文件夹中，转换结果可能会被自动上传。": "⚠ The output folder is inside a cloud-synced folder; results may be uploaded automatically.",
    "⚠ 该目录位于云同步文件夹中，转换结果可能会被自动上传。": "⚠ This folder is cloud-synced; results may be uploaded automatically.",
    "确认分享": "Confirm sharing", "共 {n} 个文件：": "{n} file(s):", "继续": "Continue",
    "请确认文件名、正文与图片内容可以分享。": "Please check that the file names, text and images are OK to share.",
    "将打包为一个 ZIP 后打开 Windows 共享。": "The files will be packed into one ZIP, then Windows Share opens.",
    "将打开 Windows 共享面板。": "Windows Share will open.", "ZIP 保存位置：": "ZIP location: ",
    "将把完整路径复制到剪贴板（不进入剪贴板历史）。": "Full paths will be copied to the clipboard (kept out of clipboard history).",
    "将把这些文件打包为 ZIP。": "These files will be packed into a ZIP.",
    "无法写入：": "Cannot write to: ", "可能没有权限，或被 Windows「受控文件夹访问」拦截（该保护会保持开启）。":
        "You may lack permission, or Windows Controlled Folder Access blocked it (that protection stays on).",
    "取消本次转换": "Cancel this job", "存到「下载」": "Save to Downloads", "选择其他目录…": "Choose another folder…",
    "常规": "General", "安全": "Security", "关于": "About", "输出目录（按日期自动建子文件夹）：": "Output folder (dated subfolders are created):",
    "输出失败时询问": "Ask when output fails",
    "写入失败时暂停，让你选择新目录、存到「下载」或取消，而不是自动改存。": "Pause on write failure and let you pick a new folder, Downloads or cancel, instead of silently redirecting.",
    "分享前确认": "Confirm before sharing",
    "打开 Windows 共享、打包 ZIP 或复制完整路径前，列出文件数量和名称；复制的内容不进入剪贴板历史和跨设备同步。":
        "List the file count and names before Windows Share, ZIP packing or copying paths; copied content stays out of clipboard history and cloud sync.",
    "移除敏感元数据": "Remove sensitive metadata",
    "去掉输出文件中的 GPS / EXIF、作者、修改者等信息（图片、Office 文档、PDF）。关闭后图片会保留原 EXIF。":
        "Strip GPS / EXIF, author and last-modified-by from outputs (images, Office files, PDF). When off, images keep the original EXIF.",
    "自动清理临时文件": "Clean temporary files automatically",
    "每次转换结束（成功、失败或中止）后删除本程序产生的中间文件。": "Delete this app's intermediate files after every job (success, failure or abort).",
    "隔离进程处理": "Process files in isolation",
    "在独立的低优先级子进程中解析文件，限制内存占用，超时会被强制中止，不影响主程序。":
        "Parse files in a separate low-priority process with a memory cap; it is killed on timeout without affecting the app.",
    "单个文件处理超时（秒）": "Per-file timeout (s)", "处理进程内存上限（MB）": "Worker memory limit (MB)",
    "文件大小上限（MB）": "Max file size (MB)", "图像像素上限（百万像素）": "Max image size (megapixels)",
    "压缩包解压后体积上限（MB）": "Max unpacked size (MB)", "定时删除生成文件": "Auto-delete outputs",
    "关闭": "Off", "{d} 天后": "After {d} days",
    "定时删除只处理输出目录中按日期命名的文件夹（如 2026-11-01），到期后移到回收站，可以还原。":
        "Only dated folders in the output folder (e.g. 2026-11-01) are affected; they go to the Recycle Bin and can be restored.",
    "立即清理临时文件": "Clean temporary files now", "有任务正在转换，请稍后再试": "A job is running, try again later",
    "已清理 {n} 项": "{n} item(s) cleaned",
    "始终开启：原文件只读不修改；结果先写入暂存文件夹，完成后再发布，同名自动编号，主窗口与悬浮球同时转换也不会互相覆盖；表格输出防公式注入（以 = + - @ 开头的文本按纯文本写入，负数仍是数字）。":
        "Always on: source files are read-only; results are written to a staging folder and published only when complete, numbered on name clashes so the main window and floating ball never overwrite each other; spreadsheet output is protected against formula injection (text starting with = + - @ is written as plain text, negatives stay numbers).",
    "配置文件：": "Config: ", "临时文件：": "Temp files: ",
    "以下 {n} 个日期文件夹已超过 {d} 天，确定后会移到回收站：": "These {n} dated folder(s) are older than {d} days and will be moved to the Recycle Bin:",
    "悬浮球": "Floating ball", "常用格式…": "Quick formats…", "常用格式": "Quick formats", "深色模式": "Dark mode",
    "已选 {n}/{m}": "{n}/{m} selected", "收起菜单": "Collapse", "主页": "Home", "外观": "Appearance", "背景色调": "Background tint", "按键高光色": "Accent color", "默认": "Default", "石墨": "Graphite", "深海": "Ocean", "森林": "Forest", "暖沙": "Sand", "暮紫": "Dusk", "玫瑰": "Rose", "蓝": "Blue", "紫": "Violet", "青": "Teal", "绿": "Green", "橙": "Orange", "粉": "Pink", "红": "Red", "点击即可预览；保存设置后生效，不保存则恢复原来的颜色。深色 / 浅色模式都会套用。": "Click to preview. Saved with the settings; leaving without saving restores the previous colors. Applies to both dark and light mode.", "悬浮球上显示的格式（最多 6 种）": "Formats shown on the floating ball (max 6)", "悬浮球 · 常用格式": "Floating ball · Quick formats", "已开启": "on", "已关闭": "off", "展开菜单": "Expand", "未保存的修改": "Unsaved changes",
    "设置已修改但尚未保存，是否保存后再退出？": "Settings were changed but not saved. Save before leaving?",
    "继续编辑": "Keep editing", "不保存": "Don't save", "保存": "Save", "点击下方格式加入悬浮球": "Click formats below to add them to the floating ball", "完成后自动打开输出文件夹": "Open output folder when done", "常用格式设置": "Quick format settings", "设置": "Settings",
    "关闭格式转换器": "Close Format Converter", "点击 ✕ 关闭窗口时，你希望：": "When you click ✕ to close the window:",
    "此选择会被记住，之后可在主页「设置」中修改。": "Your choice is remembered; change it later under “Settings”.",
    "隐藏到系统托盘": "Hide to system tray", "点击 ✕ 关闭主窗口时：": "When clicking ✕ on the main window:",
    "隐藏到系统托盘（悬浮球与托盘继续可用）": "Hide to the system tray (ball and tray stay available)", "编辑常用格式": "Edit quick formats", "清空文件": "Clear files",
    # 模块
    "① 输入文件": "① Input files", "② 目标格式": "② Target format", "③ 转换结果": "③ Results",
    "拖入文件或文件夹到窗口任意位置（可多选，Delete 键移除）":
        "Drop files or folders anywhere in the window (multi-select, Delete to remove)",
    "点击格式即开始批量转换列表中的全部文件": "Click a format to convert every file in the list",
    "双击文件直接打开；可多选后批量打开、定位或分享": "Double-click to open; multi-select to open, locate or share in bulk",
    "共 {n} 个文件": "{n} file(s)", "共 {n} 个结果": "{n} result(s)",
    "打开": "Open", "定位": "Locate", "分享": "Share", "全选": "All", "清空记录": "Clear",
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
        ("欢迎使用格式转换器", "添加文件，选择目标格式并点击「开始转换」，然后在结果里打开或分享。下面带你认识每个模块。", None),
        ("左侧菜单栏", "所有功能都在左侧菜单：主页、悬浮球、预设、任务、历史，以及底部的使用引导、帮助手册和设置。"
                       "点任意一项直接切换页面，点「主页」回到这里。最上方的「≡」可收起菜单，只显示图标，鼠标停在图标上会提示名称。", "side"),
        ("① 输入文件", "把文件或文件夹拖到窗口任意位置，或点「添加文件」。支持多选，选中后按 Delete 或「移除所选」可删掉。", "in"),
        ("② 目标格式", "在左侧选分类，在右侧选格式或预设，再点「开始转换」，即可处理列表里的全部文件。", "fmt"),
        ("③ 转换结果", "转换好的文件显示在这里：双击直接打开，多选后可批量打开、定位到文件夹或分享。", "out"),
        ("悬浮球与托盘", "点左侧菜单「悬浮球」这一行即可开关屏幕边缘悬浮球（右侧开关显示当前状态），"
                         "下方的「常用格式」决定气泡上显示哪些格式。把文件拖到气泡上就能快速转换。", "side"),
        ("外观与托盘", "标题栏的月亮开关切换深色 / 浅色，「设置 → 外观」可更换背景色调和按键高光色。"
                       "关闭窗口时程序可隐藏到右下角托盘，右键托盘图标即可打开各项功能。标题栏的「?」随时查看帮助。", None),
    ],
    "en": [
        ("Welcome to Format Converter", "Add files, choose a target format and click Start, then open or share the results. "
                                        "Here is a quick look at each panel.", None),
        ("Sidebar", "Everything lives in the left sidebar: Home, Floating ball, Presets, Tasks, History, and Quick tour, "
                    "Manual and Settings at the bottom. Click an item to switch pages; “Home” brings you back here. "
                    "“≡” at the top collapses the sidebar to icons — hover an icon to see its name.", "side"),
        ("① Input files", "Drop files or folders anywhere in the window, or click “Add files”. Select several and press "
                          "Delete or “Remove” to take them out.", "in"),
        ("② Target format", "Pick a category on the left and a format or preset on the right. Click Start to convert all files in the list.", "fmt"),
        ("③ Results", "Converted files appear here. Double-click to open; multi-select to open, locate or share.", "out"),
        ("Floating ball", "Click the “Floating ball” row in the sidebar to turn the screen-edge ball on or off (its switch shows the state). "
                          "“Quick formats” below it chooses which formats the bubble offers. Drop files on the ball for quick conversions.", "side"),
        ("Appearance & tray", "The moon switch in the title bar toggles dark / light; Settings → Appearance changes the background tint and accent color. "
                              "When the window is closed the app can hide in the system tray — right-click its icon for quick actions. "
                              "Click “?” in the title bar for help at any time.", None),
    ],
}

HELP = {"zh": [
("快速上手", """
<h2>快速上手</h2>
<p>三步完成一次转换：</p>
<ol><li><b>添加文件</b>：把文件或文件夹拖到窗口任意位置，或点「① 输入文件」下的「添加文件」「添加文件夹」。文件夹会递归加入其中全部文件。</li>
<li><b>选择格式</b>：在「② 目标格式」左侧先选类别（图像 / 文档 / 表格 / 向量 / 视频 / 预设），再在右侧选具体格式。</li>
<li><b>开始转换</b>：点右下角「开始转换 → 格式」。列表里的<b>全部</b>文件都会转换，结果出现在「③ 转换结果」。</li></ol>
<p>先选格式、再点开始，是为了避免误点格式就直接生成文件。第一次使用可以点左侧菜单底部的「使用引导」跟着走一遍。</p>
"""),
("输入文件", """
<h2>输入文件</h2>
<ul><li>几乎任何文件都能拖入：图片、PDF、Word / ODT / RTF、Excel / CSV、文本、HTML、音频、视频等。</li>
<li>无法识别内容的文件不会报错，而是生成「文件信息 + 十六进制预览」，结果标为「仅生成预览」。</li>
<li>按住 Ctrl / Shift 多选，按 <b>Delete</b> 或「移除所选」删除；「清空」移除全部。</li>
<li>转换过程中可以继续拖入文件，它们会进入下一批。</li>
<li>原文件始终只读，不会被修改或覆盖。</li></ul>
"""),
("图像 / 文档 / 表格 / 向量", """
<h2>图像、文档、表格、向量</h2>
<h3>图像（30 种）</h3>
<ul><li>PNG、JPG、WEBP、TIFF、ICO、HEIC、AVIF、PSD、EXR 等。</li>
<li>多页文档（PDF、Word）每页输出一张图片，最多 200 页；动图每帧一张，最多 100 帧。</li>
<li>视频转 GIF / WEBP 会生成动图：每秒 10 帧，默认最长边 480 像素，最多 10 秒；转其他图像格式只取一帧画面。</li></ul>
<h3>文档（17 种）</h3>
<ul><li>PDF、DOCX、DOC、RTF、ODT、XPS、DJVU 等。会提取文字、表格和图片后重新排版，原字体和版式不保留。</li>
<li>DOC / DOT 等旧格式需要本机安装 Microsoft Word；DJVU 需要 DjVuLibre；JBG 需要 JBIG-KIT。</li></ul>
<h3>表格（3 种）</h3>
<ul><li>XLSX、XLSM、CSV。Excel 按工作表导出，PDF / Word 中识别到的每张表各成一个工作表，合并单元格会保留。</li>
<li>公式按计算结果导出；以 = + - @ 开头的文字按纯文本写入，防止公式注入。</li></ul>
<h3>向量（11 种）</h3>
<ul><li>SVG、AI、EPS、PS、EMF、WMF 等。PDF / AI 转 SVG、AI 是真矢量；其他来源以图像嵌入或像素描摹，不是真矢量。</li></ul>
"""),
("视频转换", """
<h2>视频转换</h2>
<p>在「② 目标格式 → 视频」中先选<b>视频编码</b>，再选<b>格式（封装）</b>。编码决定画质、体积和兼容性，格式决定扩展名和能装哪些编码。</p>
<h3>支持的格式</h3>
<p>MP4、MOV、MKV、WEBM、AVI、WMV、FLV、TS、MTS、M2TS、MPG、MPEG、3GP、VOB。</p>
<h3>编码怎么选</h3>
<ul><li><b>自动</b>：按格式选最常用的编码（MP4 / MOV / MKV → H.264，WEBM → VP9，MPG / VOB → MPEG-2，WMV → WMV8）。不确定时用它。</li>
<li><b>H.264</b>：兼容性最好，手机、电脑、剪辑软件都能打开。</li>
<li><b>H.265 / AV1</b>：同等画质下体积更小，但部分旧设备和剪辑软件打不开。</li>
<li><b>VP9 / VP8</b>：网页视频常用，适合 WEBM。</li>
<li><b>ProRes / DNxHR</b>：专业剪辑用的中间编码，画质高、文件很大，适合放进 MOV 交给剪辑软件。</li>
<li><b>MPEG-2</b>：DVD 和老设备；<b>MJPEG</b>：老式摄像设备。</li>
<li><b>保持原编码</b>：不重新编码，只换封装，速度最快且画质无损（例如 MKV 里的 H.264 直接换成 MP4）。</li></ul>
<h3>注意</h3>
<ul><li>所选编码放不进该格式时（例如 MP4 + ProRes），会自动改用推荐编码，结果标为「部分输出」并说明原因。</li>
<li>只保留第 1 条音轨，字幕不保留；手机竖拍视频会自动转正。</li>
<li>预设中可以保存视频编码和最长边（用于缩小分辨率）；质量数值越高画质越好、文件越大。</li>
<li>视频转码较慢，超时时间为普通文件的 12 倍；视频文件大小上限至少 4 GB。</li></ul>
"""),
("转换结果与输出", """
<h2>转换结果与输出</h2>
<ul><li><b>双击</b>结果用默认程序打开；多选后可批量「打开」「定位」（在资源管理器中选中）或「分享」。</li>
<li>分享方式：Windows 共享面板、复制文件（可直接粘贴到微信 / QQ / 邮件）、复制路径、打包为 ZIP。</li>
<li>每个结果会标注：<b>完整转换</b>、<b>部分输出</b>（有内容无法保留，悬停看原因）、<b>仅生成预览</b>、<b>失败</b>，以及元数据是否已清理。</li>
<li>「清空记录」只清除列表，不删除文件。</li></ul>
<h3>输出位置</h3>
<ul><li>默认输出到 <code>用户目录\\格式转换输出\\日期</code>，每天自动新建日期文件夹；可在「设置 → 常规」修改根目录。</li>
<li>同名文件不会覆盖，会自动加 (2)、(3)… 编号。</li>
<li>输出目录无法写入时（例如被 Windows「受控文件夹访问」拦截），会暂停并让你选择其他目录、存到「下载」或取消。</li>
<li>输出目录在 OneDrive 等云同步文件夹中时，设置里会提示结果可能被自动上传。</li></ul>
"""),
("预设与任务", """
<h2>预设与任务</h2>
<h3>预设</h3>
<ul><li>左侧菜单「预设」保存常用的格式和参数：质量、最长边、页码 / 帧（如 1-3,5）、视频编码。</li>
<li>保存后可在「② 目标格式 → 预设」中一键使用，也可以加入悬浮球的常用格式。</li></ul>
<h3>任务</h3>
<ul><li>左侧菜单「任务」列出主窗口和悬浮球发起的全部批量任务，可展开看每个文件的状态和错误说明。</li>
<li>进行中的任务可以取消（已完成的结果会保留），结束后可以只重试失败的文件。</li></ul>
<h3>历史记录</h3>
<ul><li>转换成功的源文件会自动移出「① 输入文件」；在结果列表中打开过的文件也会移出「③ 转换结果」，都归档到左侧菜单「历史」。</li>
<li>「历史」按日期以时间线展示每次转换，可搜索文件名，并直接打开或定位生成的文件。</li>
<li>保留时间在「设置 → 安全 → 历史记录保留时间」中设置（7 / 30 / 90 / 180 / 365 天），超过的记录会被清除，文件本身不会删除。</li></ul>
"""),
("悬浮球与托盘", """
<h2>悬浮球与系统托盘</h2>
<h3>悬浮球</h3>
<ul><li>点左侧菜单「悬浮球」这一行开启或关闭，右侧的开关显示当前状态（菜单收起时显示在图标右下角）。</li>
<li>「悬浮球」下方缩进的「常用格式」只作用于悬浮球：最多选 6 种格式或预设，显示在气泡上。</li>
<li>把文件拖到悬浮球上，再点常用格式即可转换，不必打开主窗口。</li>
<li>悬浮球吸附在屏幕左、右或顶部边缘，拖动可换位置；右键可打开主窗口、查看任务、编辑常用格式、锁定或重置位置、退出。</li>
<li>「常用格式」底部可开启「完成后自动打开输出文件夹」。</li></ul>
<h3>系统托盘</h3>
<ul><li>程序运行时右下角显示托盘图标，单击打开主窗口，右键可快速添加文件、打开输出文件夹、开关悬浮球、退出。</li>
<li>第一次点 ✕ 时会询问「完全退出」还是「隐藏到系统托盘」，之后按你的选择执行，可在「设置 → 常规」修改。</li></ul>
"""),
("设置与安全", """
<h2>设置与安全</h2>
<ul><li><b>常规</b>：关闭方式、输出目录。</li>
<li><b>外观</b>：背景色调（默认、石墨、深海、森林、暖沙、暮紫、玫瑰）和按键高光色（蓝、紫、青、绿、橙、粉、红），点击即预览，深色 / 浅色都会套用。</li>
<li>修改设置后未保存就离开，会弹出提示：保存、不保存或继续编辑；不保存时颜色等会恢复原样。</li>
<li><b>安全</b>：输出失败时询问、分享前确认、移除敏感元数据（GPS / EXIF、作者等）、自动清理临时文件、隔离进程处理。</li>
<li><b>资源与清理</b>：单个文件超时、处理进程内存上限、文件大小 / 像素 / 解压体积上限、定时删除生成文件、立即清理临时文件。</li>
<li>定时删除只处理本程序生成并记录在清单中、超过天数且未被修改的文件，移到回收站，可以还原。</li>
<li>始终开启：原文件只读；结果先写入暂存文件夹，完成后再发布；主窗口与悬浮球同时转换也不会互相覆盖。</li></ul>
"""),
("界面与快捷键", """
<h2>界面与快捷键</h2>
<ul><li>所有功能都在同一个窗口内打开，通过<b>左侧菜单栏</b>切换；点「主页」或按 <b>Esc</b> 回到主页。</li>
<li>菜单最上方的「≡」收起 / 展开菜单：收起时只显示图标，鼠标停留会提示名称；状态会被记住。</li>
<li>任务运行时，「任务」图标上出现蓝点并显示进行中的数量。</li>
<li>标题栏的月亮开关切换<b>深色 / 浅色</b>模式，配色可在「设置 → 外观」更换，选择都会被记住。</li>
<li>「EN / 中文」切换界面语言，悬浮球和托盘同步切换。</li>
<li><b>F1</b> 打开本手册；<b>Delete</b> 移除输入列表中选中的文件。</li>
<li>拖动窗口边缘可调整大小；窗口太小时内容区才会出现滚动条。</li>
<li>设置保存在 <code>%APPDATA%\\格式转换器\\config.json</code>。</li></ul>
"""),
("常见问题", """
<h2>常见问题</h2>
<h3>结果显示「部分输出」？</h3>
<p>转换完成，但有部分内容无法保留（例如文档重新排版、视频编码被自动更换、字幕未保留）。悬停在结果上或打开「任务」可看具体说明。</p>
<h3>结果显示「仅生成预览」？</h3>
<p>来源无法完整转换为目标类型，例如音频转图片、视频转 PNG（只取一帧）、无法识别的文件。</p>
<h3>提示「超时」或「超出内存上限」？</h3>
<p>文件过大或过复杂。可在「设置 → 资源与清理」调高超时和内存上限，或关闭「隔离进程处理」。</p>
<h3>转出的视频在某些设备上打不开？</h3>
<p>改用 MP4 + H.264，这是兼容性最好的组合。H.265、AV1、ProRes 在部分设备上不受支持。</p>
<h3>DOC / DJVU / JBG 转换失败？</h3>
<p>DOC、DOT 需要本机安装 Microsoft Word；DJVU 需要 DjVuLibre；JBG 需要 JBIG-KIT。</p>
"""),
], "en": [
("Quick start", """
<h2>Quick start</h2>
<ol><li><b>Add files</b>: drop files or folders anywhere in the window, or use “Add files” / “Add folder” (folders are added recursively).</li>
<li><b>Pick a format</b>: in “② Target format”, choose a category on the left (Image / Document / Spreadsheet / Vector / Video / Presets), then a format on the right.</li>
<li><b>Start</b>: click “Start → format”. <b>All</b> listed files are converted and appear in “③ Results”.</li></ol>
<p>Picking first and then clicking Start prevents accidental conversions. Use “Quick tour” at the bottom of the sidebar for a walkthrough.</p>
"""),
("Input files", """
<h2>Input files</h2>
<ul><li>Almost anything can be dropped: images, PDF, Word / ODT / RTF, Excel / CSV, text, HTML, audio, video.</li>
<li>Unrecognised files produce a file-info + hex preview, marked “Preview only”.</li>
<li>Ctrl / Shift to multi-select, <b>Delete</b> or “Remove” to remove; “Clear” removes everything.</li>
<li>Files dropped during a conversion go into the next batch. Source files are never modified.</li></ul>
"""),
("Image / document / sheet / vector", """
<h2>Image, document, spreadsheet, vector</h2>
<ul><li><b>Image (30)</b>: PNG, JPG, WEBP, TIFF, ICO, HEIC, AVIF, PSD, EXR… One image per page (max 200) or frame (max 100). Video → GIF / WEBP gives an animation (10 fps, 480 px, up to 10 s); other image formats take one frame.</li>
<li><b>Document (17)</b>: PDF, DOCX, DOC, RTF, ODT, XPS, DJVU… Text, tables and pictures are re-laid out; original fonts and layout are not kept. DOC needs Microsoft Word; DJVU needs DjVuLibre; JBG needs JBIG-KIT.</li>
<li><b>Spreadsheet (3)</b>: XLSX, XLSM, CSV. Each table found becomes a sheet; merged cells kept; formulas exported as values with formula-injection protection.</li>
<li><b>Vector (11)</b>: SVG, AI, EPS, PS, EMF, WMF… PDF / AI → SVG / AI is true vector; other sources embed an image or are traced.</li></ul>
"""),
("Video", """
<h2>Video conversion</h2>
<p>In “② Target format → Video”, choose a <b>video codec</b>, then a <b>format (container)</b>.</p>
<p>Formats: MP4, MOV, MKV, WEBM, AVI, WMV, FLV, TS, MTS, M2TS, MPG, MPEG, 3GP, VOB.</p>
<ul><li><b>Auto</b>: the usual codec for the format (H.264 for MP4 / MOV / MKV, VP9 for WEBM, MPEG-2 for MPG / VOB).</li>
<li><b>H.264</b>: plays everywhere. <b>H.265 / AV1</b>: smaller files, less compatible. <b>VP9 / VP8</b>: web video.</li>
<li><b>ProRes / DNxHR</b>: editing intermediates, large files, best in MOV. <b>MPEG-2</b>: DVD; <b>MJPEG</b>: old cameras.</li>
<li><b>Keep original codec</b>: remux only — fastest and lossless.</li>
<li>If a codec doesn't fit the format, the recommended codec is used and the result is marked “Partial output”.</li>
<li>Only the first audio track is kept; subtitles are dropped; portrait phone videos are rotated upright.</li>
<li>Video jobs get 12× the normal timeout and at least a 4 GB size limit.</li></ul>
"""),
("Results & output", """
<h2>Results & output</h2>
<ul><li><b>Double-click</b> to open; multi-select to Open, Locate or Share (Windows Share, copy files, copy paths, ZIP).</li>
<li>Each result is labelled Complete / Partial output / Preview only / Failed, plus its metadata status.</li>
<li>Default output: <code>%USERPROFILE%\\格式转换输出\\date</code>; change it in Settings → General. Existing files are never overwritten.</li>
<li>If the folder isn't writable, the job pauses and lets you choose another folder, Downloads, or cancel.</li></ul>
"""),
("Presets & tasks", """
<h2>Presets & tasks</h2>
<ul><li>“Presets” in the sidebar saves a format with quality, longest side, pages / frames and video codec. Use them under “② Target format → Presets” or on the floating ball.</li>
<li>“Tasks” in the sidebar lists every batch from the main window and floating ball with per-file status; cancel running jobs or retry only failed files.</li></ul>
<h3>History</h3>
<ul><li>Successfully converted sources leave “① Input files”, and results you open leave “③ Results” — both are archived to “History” in the sidebar.</li>
<li>History shows a dated timeline; search by file name and open or locate outputs.</li>
<li>Retention is set in Settings → Security → Keep history for (7–365 days); older records are removed, files are kept.</li></ul>
"""),
("Floating ball & tray", """
<h2>Floating ball & tray</h2>
<ul><li>Click the “Floating ball” row in the sidebar to turn it on or off; its switch shows the state (on the icon when the sidebar is collapsed).</li>
<li>“Quick formats”, indented under it, applies only to the ball: choose up to 6 formats or presets. Drop files on the ball and click a format to convert.</li>
<li>It docks to the left, right or top edge; right-click for the main window, tasks, quick formats, lock / reset position, quit.</li>
<li>The tray icon opens the window; right-click for quick actions. The first ✕ asks whether to quit or hide to the tray.</li></ul>
"""),
("Settings & security", """
<h2>Settings & security</h2>
<ul><li><b>General</b>: close behaviour, output folder.</li>
<li><b>Appearance</b>: background tint (Default, Graphite, Ocean, Forest, Sand, Dusk, Rose) and accent color (Blue, Violet, Teal, Green, Orange, Pink, Red). Click to preview; applies to dark and light mode.</li>
<li>Leaving with unsaved changes asks: Save, Don't save or Keep editing. Not saving restores the previous colors.</li>
<li><b>Security</b>: ask on output failure, confirm before sharing, strip metadata, auto-clean temp files, isolated processing.</li>
<li><b>Resources & cleanup</b>: timeout, memory, size / pixel / unpack limits, auto-delete outputs (Recycle Bin, only files this app recorded).</li></ul>
"""),
("Interface & shortcuts", """
<h2>Interface & shortcuts</h2>
<ul><li>Everything opens inside the one window and is switched from the <b>sidebar</b>; “Home” or <b>Esc</b> returns to the main page.</li>
<li>“≡” at the top collapses / expands the sidebar; collapsed shows icons only (hover for names). The choice is remembered.</li>
<li>While tasks run, the Tasks icon shows a blue dot and the running count.</li>
<li>The moon switch in the title bar toggles <b>dark / light</b> mode; colors are changed in Settings → Appearance.</li>
<li>“EN / 中文” switches language. <b>F1</b> opens this manual; <b>Delete</b> removes selected input files.</li>
<li>Settings live in <code>%APPDATA%\\格式转换器\\config.json</code>.</li></ul>
"""),
("FAQ", """
<h2>FAQ</h2>
<h3>“Partial output”?</h3><p>Converted, but something couldn't be kept (layout, codec swapped, subtitles). Hover the result or open Tasks for details.</p>
<h3>“Preview only”?</h3><p>The source can't fully become the target type, e.g. audio → image, video → PNG (one frame).</p>
<h3>Timeout or memory limit?</h3><p>Raise the limits in Settings → Resources & cleanup, or turn off isolated processing.</p>
<h3>Video won't play on a device?</h3><p>Use MP4 + H.264 for maximum compatibility.</p>
"""),
]}

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


HISTORY_FILE = os.path.join(os.path.dirname(CONFIG), "history.json")


def load_history():
    try:
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(items):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    tmp = HISTORY_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False)
    os.replace(tmp, HISTORY_FILE)


def add_history(entries, days):
    """追加转换记录，并删除超过保留天数的旧记录（只删记录，不删文件）。"""
    cut = time.time() - days * 86400
    items = [h for h in load_history() if h.get("t", 0) >= cut] + entries
    save_history(items[-5000:])


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


def synced_dir(path):
    """输出目录是否在 OneDrive 等云同步文件夹里（结果可能被自动上传）。"""
    p = os.path.normcase(os.path.abspath(path))
    for k in SYNC_ENV:
        v = os.environ.get(k)
        if v and p.startswith(os.path.normcase(os.path.abspath(v))):
            return True
    return any(x in p for x in ("\\onedrive", "\\dropbox", "\\google drive", "我的云端硬盘", "\\icloud"))


def private_mime(md):
    """程序写入剪贴板的内容不进入 Windows 剪贴板历史，也不跨设备同步。"""
    for name in ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory",
                 "CanUploadToCloudClipboard"):
        md.setData(f'application/x-qt-windows-mime;value="{name}"', QByteArray(b"\0\0\0\0"))
    return md


def show_in_folder(paths):
    if not paths:
        return
    if len(paths) == 1:
        subprocess.Popen(f'explorer /select,"{paths[0]}"')
        return
    os.startfile(os.path.dirname(paths[0]))


class Worker(QThread):
    progress = pyqtSignal(int, str)
    file_done = pyqtSignal(int, dict)
    finished_all = pyqtSignal(list, list)
    ask_dir = pyqtSignal(str)

    def __init__(self, files, out_root, fmt, kind, cfg, params=None):
        super().__init__()
        self.files, self.out_root, self.fmt, self.kind, self.cfg = files, out_root, fmt, kind, cfg
        self.params = params or {}
        self.blocked = False      # 自动改存到「下载」
        self.redirect = None      # 用户另选的目录
        self._ev = threading.Event()
        self.answer = None
        self.cancel_ev = threading.Event()
        self.limit_problem = ""

    def answer_dir(self, d):
        self.answer = d
        self._ev.set()

    def cancel(self):
        self.cancel_ev.set()
        self.answer_dir(None)

    def run(self):
        ok, bad = [], []
        root = self.out_root
        runner = safejob.Runner(self.cfg) if self.cfg["isolate"] else None
        try:
            for i, f in enumerate(self.files):
                name = os.path.basename(f)
                info = {"src": f, "state": "cancelled", "files": [], "meta": {}, "level": "", "notes": [], "error": ""}
                if self.cancel_ev.is_set():
                    self.file_done.emit(i, info)
                    continue
                self.progress.emit(i, f"{tr('正在转换')} {name} → {self.fmt} …")
                while True:
                    try:
                        r = safejob.convert_one(f, os.path.join(root, time.strftime("%Y-%m-%d")), self.fmt, self.kind,
                                                self.cfg, self.params, runner, self.cancel_ev)
                        info.update(r, state=r["level"])
                        ok += r["files"]
                    except safejob.Cancelled:
                        pass
                    except safejob.OutputBlocked:
                        # 输出目录写不进（多半是「受控文件夹访问」拦截）
                        if self.cfg["ask_on_fail"]:
                            self._ev.clear()
                            self.ask_dir.emit(root)
                            self._ev.wait()
                            if not self.answer:
                                self.cancel_ev.set()
                                break
                            root = self.redirect = self.answer
                            continue
                        if root != FALLBACK_OUT:
                            root, self.blocked = FALLBACK_OUT, True
                            continue
                        info.update(state="failed", error=tr("输出目录无法写入"))
                    except Exception as e:
                        traceback.print_exc()
                        info.update(state="failed", error=tr_err(str(e)))
                    break
                if info["state"] == "failed":
                    bad.append(f"{name}: {info['error']}")
                self.file_done.emit(i, info)
        finally:
            if runner:
                runner.close()
                self.limit_problem = runner.limit_problem
        self.finished_all.emit(ok, bad)


class TitleBar(QWidget):
    def __init__(self, win):
        super().__init__(objectName="title")
        self.win = win
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 6, 0)
        lay.setSpacing(2)
        ic = QLabel()
        ic.setPixmap(QPixmap(os.path.join(ASSETS, "icon.png")).scaled(
            18, 18, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(ic)
        self.text = QLabel(objectName="titleText")
        lay.addSpacing(6)
        lay.addWidget(self.text)
        lay.addSpacing(6)
        lay.addWidget(QLabel("v" + VERSION, objectName="version"))
        lay.addStretch()
        self.theme_icon = QLabel("", objectName="themeIcon")   # 月亮
        lay.addWidget(self.theme_icon)
        lay.addSpacing(4)
        self.theme_switch = Switch(small=True)
        self.theme_switch.setChecked(THEME == "dark")
        self.theme_switch.setToolTip(tr("深色模式"))
        self.theme_icon.setToolTip(tr("深色模式"))
        self.theme_switch.toggled.connect(lambda on: win.set_theme("dark" if on else "light"))
        lay.addWidget(self.theme_switch, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(8)
        self.btn_help = QPushButton("", objectName="help")
        self.btn_help.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_help.clicked.connect(win.open_help)
        lay.addWidget(self.btn_help)
        self.btn_lang = QPushButton(objectName="lang")
        self.btn_lang.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_lang.clicked.connect(win.toggle_lang)
        lay.addWidget(self.btn_lang)
        lay.addSpacing(6)
        lay.addWidget(QFrame(objectName="titleSep"), 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addSpacing(6)
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
        self.resize(1080, 740)
        self.setMinimumSize(900, 660)
        self._ov_cursor = None
        QApplication.instance().installEventFilter(self)          # 边缘按下 → 系统缩放
        self.edge_timer = QTimer(self, interval=40, timeout=self.poll_edges)   # 边缘 / 角落光标
        self.edge_timer.start()
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
        # 所有界面都在这个堆栈里切换：0 = 主页，其余为设置、预设、任务等页面
        self.pages = QStackedWidget()
        self.page_stack = []
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(0)
        self.mid = mid
        fl.addLayout(mid, 1)
        mid.addWidget(self.pages, 1)
        body = QWidget(objectName="pageBody")   # 主页：最小窗口尺寸保证完整显示，不需要滚动条
        self.pages.addWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(12, 4, 12, 12)
        root.setSpacing(10)

        # 左侧可折叠导航栏：折叠时只显示图标，展开时显示图标 + 文字
        self.ball_switch = Switch()   # 不显示，仅作为悬浮球开关状态
        self.ball_switch.setChecked(bool(self.cfg.get("ball_on")))
        self.ball_switch.toggled.connect(self.set_ball)
        self.side = QFrame(objectName="side")
        sl = QVBoxLayout(self.side)
        sl.setContentsMargins(6, 8, 6, 8)
        sl.setSpacing(4)
        self.side_btns = []
        def item(glyph, key, fn=None, checkable=False, nav=False):
            b = SideButton(glyph, key)
            b.setCheckable(checkable)
            if fn and nav:
                b.clicked.connect(lambda _=None, fn=fn: self.side_go(fn))
            elif fn:
                b.clicked.connect(fn)
            sl.addWidget(b)
            self.side_btns.append(b)
            return b
        self.btn_fold = item("", "收起菜单", self.toggle_side)
        sep = QFrame(objectName="sideSep")
        sep.setFixedHeight(1)
        sl.addWidget(sep)
        item("", "主页", self.go_home)
        self.btn_ball = item("", "悬浮球", lambda: self.ball_switch.setChecked(self.btn_ball.isChecked()), True)
        self.btn_ball.is_switch = True
        self.btn_ball.setChecked(self.ball_switch.isChecked())
        self.ball_switch.toggled.connect(lambda on: self.btn_ball.setToolTip(
            tr("悬浮球") + ("：" + tr("已开启") if on else "：" + tr("已关闭")) if not self.side_open else ""))
        self.ball_switch.toggled.connect(self.btn_ball.setChecked)
        sub = item("", "常用格式", self.open_ball_settings, nav=True)
        sub.child = True   # 悬浮球的子项：缩进 + 连接线，表明只作用于悬浮球
        sub.setFixedHeight(32)
        item("", "预设", self.open_presets, nav=True)
        self.btn_tasks = item("", "任务", self.open_tasks, nav=True)
        item("", "历史", self.open_history, nav=True)
        sl.addStretch()
        item("", "使用引导", self.open_guide, nav=True)
        item("", "帮助手册", self.open_help, nav=True)
        item("", "设置", self.open_settings, nav=True)
        self.set_side(bool(self.cfg.get("side_open", True)), save=False)

        top = QHBoxLayout()
        top.setSpacing(10)
        root.addLayout(top, 4)

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
        prog = QWidget()
        ph = QHBoxLayout(prog)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(8)
        self.prog_lbl = QLabel(objectName="hint")
        self.bar = QProgressBar(textVisible=False, objectName="mini")
        self.bar.setRange(0, 1000)
        self.bar.setFixedWidth(150)
        ph.addWidget(self.prog_lbl)
        ph.addWidget(self.bar)
        self.prog_box = prog
        prog.hide()
        self.bar_anim = QPropertyAnimation(self.bar, b"value", self)
        self.bar_anim.setDuration(380)
        self.bar_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.prog_timer = QTimer(self, interval=60, timeout=self.creep)
        self.prog = [0.0, 1.0]
        self.card_out, v = self.card("③ 转换结果", "双击文件直接打开；可多选后批量打开、定位或分享", prog)
        self.sync_warn = QLabel(objectName="warn")
        self.sync_warn.setWordWrap(True)
        v.addWidget(self.sync_warn)
        self.results = FileList(deletable=True, objectName="results")
        self.results.itemDoubleClicked.connect(lambda it: self.open_result(it.data(Qt.ItemDataRole.UserRole)))
        self.results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self.results_menu)
        self.results.model().rowsInserted.connect(self.update_counts)
        self.results.model().rowsRemoved.connect(self.update_counts)
        self.results.setMinimumHeight(90)
        v.addWidget(self.results, 1)
        rrow = QHBoxLayout()
        self.btn_open = self.L(QPushButton(), "打开")
        self.btn_open.clicked.connect(self.open_selected)
        self.btn_locate = self.L(QPushButton(), "定位")
        self.btn_locate.clicked.connect(self.locate)
        self.btn_share = self.L(QPushButton(objectName="primary"), "分享", " ▾")
        self.btn_share.clicked.connect(lambda: self.share_menu().exec(
            self.btn_share.mapToGlobal(QPoint(0, self.btn_share.height()))))
        self.btn_all = self.L(QPushButton(), "全选")
        self.btn_all.clicked.connect(self.results.selectAll)
        self.btn_clr = self.L(QPushButton(), "清空记录")
        self.btn_clr.clicked.connect(self.results.clear)
        for b in (self.btn_open, self.btn_locate, self.btn_share, self.btn_all, self.btn_clr):
            rrow.addWidget(b)
        rrow.setSpacing(6)
        rrow.addStretch()
        v.addLayout(rrow)
        srow = QHBoxLayout()   # 结果数量放到状态行右侧，按钮行留足宽度
        self.status = self.L(QLabel(), "就绪")
        self.status.setWordWrap(True)
        self.status.setOpenExternalLinks(True)
        srow.addWidget(self.status, 1)
        self.out_count = QLabel(objectName="hint")
        srow.addWidget(self.out_count, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(srow)
        top.addWidget(self.card_out, 1)

        # ---- ② 目标格式
        self.card_fmt, v = self.card("② 目标格式", "先选择目标格式，再点「开始转换」，避免点错格式直接生成")
        sel = QHBoxLayout()
        cats = QFrame(objectName="cats")   # 父级：类别导航
        cats.setFixedWidth(160)
        cl = QVBoxLayout(cats)
        cl.setContentsMargins(6, 6, 6, 6)
        cl.setSpacing(4)
        self.stack = QStackedWidget()
        self.fmt_buttons = []
        groups = (("图像", "image", converter.IMAGE_FORMATS), ("文档", "doc", converter.DOC_FORMATS),
                  ("表格", "sheet", converter.SHEET_FORMATS), ("向量", "vector", converter.VECTOR_FORMATS),
                  ("视频", "video", converter.VIDEO_FORMATS))
        self.cat_kinds = [g[1] for g in groups] + ["preset"]
        self.cat_btns = []
        for idx, (name, kind, fmts) in enumerate(groups):
            cb = self.nav_button(name, len(fmts))
            cb.clicked.connect(lambda _, i=idx: self.show_cat(i))
            cb.setChecked(idx == 0)
            cl.addWidget(cb)
            self.cat_btns.append(cb)
            page = QWidget()
            g = QGridLayout(page)
            g.setContentsMargins(0, 0, 0, 0)
            g.setSpacing(7)
            row0 = 0
            if kind == "video":   # 视频：格式（容器）之外再选编码
                self.vcodec = QComboBox()
                for key, label in videoconv.CODEC_CHOICES:
                    self.vcodec.addItem(tr(label), key)
                self.vcodec.currentIndexChanged.connect(self.codec_changed)
                hl = QHBoxLayout()
                hl.addWidget(self.L(QLabel(), "视频编码"))
                hl.addWidget(self.vcodec, 1)
                g.addLayout(hl, 0, 0, 1, 8)
                row0 = 1
            for k, f in enumerate(fmts):
                b = QPushButton(f, objectName="fmt", checkable=True)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _, b=b, f=f, kind=kind: self.select(b, f, kind))
                b.kind = kind
                g.addWidget(b, row0 + k // 8, k % 8)
                self.fmt_buttons.append(b)
            g.setRowStretch(g.rowCount(), 1)
            self.stack.addWidget(page)
        self.cat_preset = self.nav_button("预设", None)
        self.cat_preset.clicked.connect(lambda: self.show_cat(len(groups)))
        cl.addWidget(self.cat_preset)
        self.preset_page = QWidget()
        self.preset_grid = QGridLayout(self.preset_page)
        self.preset_grid.setContentsMargins(0, 0, 0, 0)
        self.preset_grid.setSpacing(7)
        self.stack.addWidget(self.preset_page)
        cl.addStretch()
        sel.addWidget(cats)
        sel.setSpacing(10)
        area = QFrame(objectName="fmtArea")   # 子级：该类别下的可选格式
        al = QVBoxLayout(area)
        al.setContentsMargins(10, 10, 10, 10)
        al.addWidget(self.stack)
        sel.addWidget(area, 1)
        v.addLayout(sel, 1)
        self.cap_hint = QLabel(objectName="capHint")
        self.cap_hint.setWordWrap(True)
        gr = QHBoxLayout()
        gr.addWidget(self.cap_hint, 1)
        self.btn_go = QPushButton(objectName="go")
        self.btn_go.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_go.clicked.connect(self.start_selected)
        gr.addWidget(self.btn_go, 0, Qt.AlignmentFlag.AlignBottom)
        v.addLayout(gr)
        self.sel = None
        cats.setMinimumHeight(cats.sizeHint().height())   # 类别导航按钮总高度，不允许被压缩
        self.card_fmt.setMinimumHeight(330)
        root.addWidget(self.card_fmt, 6)
        self.tasks, self.task_seq, self.task_dlg = [], 0, None
        self.result_info = {}
        self.rebuild_presets()
        self.mid.insertWidget(0, self.side)

        self.L(self.title.text, "格式转换器")
        QShortcut(QKeySequence("F1"), self, self.open_help)
        self.make_tray()
        self.retranslate()

    def nav_button(self, name, count):
        """类别导航按钮：左侧名称，右侧圆角数量徽标。"""
        b = self.L(NavButton(count), name)
        b.setFixedHeight(34)
        b.setCheckable(True)
        b.setAutoExclusive(True)
        return b

    def card(self, title, hint, extra=None):
        f = QFrame(objectName="card")
        v = QVBoxLayout(f)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        h = QHBoxLayout()
        h.addWidget(self.L(QLabel(objectName="cardTitle"), title))
        h.addStretch()
        if extra:
            h.addWidget(extra)
        v.addLayout(h)
        hl = self.L(QLabel(objectName="hint"), hint)
        hl.setWordWrap(True)
        v.addWidget(hl)
        return f, v

    def highlight(self, which):
        for key, c in (("in", self.card_in), ("fmt", self.card_fmt), ("out", self.card_out), ("side", self.side)):
            c.setProperty("hl", key == which)
            c.style().unpolish(c)
            c.style().polish(c)

    # ---- 语言
    def L(self, w, key, suffix=""):
        self.i18n.append((w, key, suffix))
        return w

    def set_side(self, open_, save=True):
        self.side_open = open_
        self.side.setFixedWidth(184 if open_ else 52)
        for b in self.side_btns:
            b.expanded = open_
            b.setToolTip("" if open_ else tr(b.key))
            b.update()
        self.btn_fold.key = "收起菜单" if open_ else "展开菜单"
        if self.isVisible():
            QTimer.singleShot(0, self.update_min)
        if save:
            self.cfg["side_open"] = open_
            self.save()

    def go_home(self):
        """关闭所有打开的页面回到主页；有页面拒绝关闭（如设置未保存选择继续编辑）时返回 False。"""
        for pg in reversed(list(self.page_stack)):
            if getattr(pg, "overlay", False):
                continue
            pg.reject()
            if pg in self.page_stack and pg.isVisible():
                return False
        return True

    def side_go(self, fn):
        if self.go_home():
            QTimer.singleShot(0, fn)   # 等已关闭页面的事件循环退出后再打开新页面

    def update_min(self):
        """窗口最小尺寸取布局实际需要的大小，保证按钮文字不被挤压。"""
        lay = self.layout()
        lay.invalidate()
        lay.activate()
        m = lay.minimumSize().expandedTo(QSize(900, 660))
        self.setMinimumSize(m)
        if self.width() < m.width() or self.height() < m.height():
            self.resize(max(self.width(), m.width()), max(self.height(), m.height()))

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.update_min)

    def toggle_side(self):
        self.set_side(not self.side_open)

    def retranslate(self):
        if hasattr(self, "side_btns"):
            self.set_side(self.side_open, save=False)
        for w, key, suffix in self.i18n:
            w.setText(tr(key) + suffix)
        self.setWindowTitle(tr("格式转换器"))
        self.title.btn_lang.setText("EN" if LANG == "zh" else "中文")
        self.title.btn_lang.setToolTip(tr("切换语言"))
        self.title.btn_help.setToolTip(tr("帮助手册") + " (F1)")
        self.update_dir_label()
        self.update_counts()
        self.build_tray_menu()
        if hasattr(self, "vcodec"):
            for i, (_, label) in enumerate(videoconv.CODEC_CHOICES):
                self.vcodec.setItemText(i, tr(label))
        if self.isVisible():
            QTimer.singleShot(0, self.update_min)
        if hasattr(self, "cap_hint"):
            self.show_cat(self.stack.currentIndex())
            self.update_go()
            self.update_task_btn()
            self.rebuild_presets()

    # ---- 应用内页面
    def push_page(self, page):
        if not self.isVisible() or self.isMinimized():
            self.show_main()
        if page.overlay:
            page.setParent(self.frame)
            page.show_()
            page.raise_()
            return
        self.pages.addWidget(page)
        self.page_stack.append(page)
        self.pages.setCurrentWidget(page)
        page.setFocus()

    def pop_page(self, page):
        if page.overlay:
            QFrame.hide(page)
            page.deleteLater() if not page.keep else None
            return
        if page in self.page_stack:
            self.page_stack.remove(page)
        self.pages.removeWidget(page)
        QFrame.hide(page)
        self.pages.setCurrentIndex(self.pages.indexOf(self.page_stack[-1]) if self.page_stack else 0)
        if not page.keep:
            page.deleteLater()

    def theme_colors(self):
        return THEMES[THEME]

    def apply_palette(self, bg=None, accent=None):
        compose_palette(bg, accent)
        QApplication.instance().setStyleSheet(build_qss(THEME))
        for w in QApplication.instance().allWidgets():
            w.update()
        if self.ball:
            self.ball.apply_theme()

    def set_theme(self, theme):
        global THEME
        THEME = theme
        self.cfg["theme"] = theme
        save_cfg(self.cfg)
        QApplication.instance().setStyleSheet(build_qss(theme))
        for w in QApplication.instance().allWidgets():
            if isinstance(w, Switch):
                w.update()
        if self.ball:
            self.ball.apply_theme()

    def toggle_lang(self):
        global LANG
        LANG = "en" if LANG == "zh" else "zh"
        self.cfg["lang"] = LANG
        save_cfg(self.cfg)
        self.i18n = [x for x in self.i18n if x[0] is not self.status] + [(self.status, "就绪", "")]
        self.retranslate()
        for pg in list(self.page_stack):
            pg.retitle()
            if hasattr(pg, "load_lang"):
                pg.load_lang()
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
        m.addAction(tr("常用格式…"), self.open_ball_settings)
        m.addSeparator()
        m.addAction(tr("使用引导"), lambda: (self.show_main(), self.open_guide()))
        m.addAction(tr("帮助手册"), self.open_help)
        m.addSeparator()
        m.addAction(tr("退出"), self.quit_app)
        self.tray.setToolTip(f"{tr('格式转换器')} v{VERSION}")

    def set_ball(self, on):
        if bool(self.cfg.get("ball_on")) == on and (self.ball is not None) == on:
            return
        self.cfg["ball_on"] = on
        self.save()
        self.apply_ball()
        if self.ball_switch.isChecked() != on:
            self.ball_switch.setChecked(on)
        self.build_tray_menu()

    def sec(self, key):
        return self.cfg.get(key, SEC_DEFAULTS[key])

    def sec_cfg(self):
        return {k: self.sec(k) for k in SEC_DEFAULTS}

    def open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec():
            dlg.apply()
            self.save()
            self.update_dir_label()
            self.run_auto_delete()

    def run_auto_delete(self):
        """定时删除：把清单中超过保留天数、且未被改动的生成文件移到回收站（有任务进行时跳过）。"""
        days = self.sec("auto_delete_days")
        if days <= 0 or self.jobs:
            return
        done = safejob.auto_delete(days)
        if done:
            self.tray.showMessage(tr("已清理过期的生成文件"),
                                  tr("{n} 个超过 {d} 天的生成文件已移到回收站").format(n=len(done), d=days),
                                  QIcon(os.path.join(ASSETS, "icon.ico")), 5000)

    def after_job(self):
        running = self.jobs or (getattr(self, "worker", None) and self.worker.isRunning())
        if self.sec("clean_temp") and not running:
            safejob.clean_temp()

    # ---- 选择格式 → 开始转换
    def select(self, b, fmt, kind, params=None, label=None):
        if kind == "video" and getattr(b, "kind", None) == "video":
            key = self.vcodec.currentData()
            params = {"vcodec": key}
            label = fmt if key == "auto" else f"{fmt} · {videoconv.CODECS.get(key, ('原编码',))[0]}"
        for x in self.fmt_buttons:
            if x is not b:
                x.setChecked(False)
        b.setChecked(True)
        self.sel = (b, fmt, kind, params, label)
        self.update_go()

    def codec_changed(self, *_):
        if self.sel and self.sel[2] == "video" and getattr(self.sel[0], "kind", None) == "video":
            self.select(self.sel[0], self.sel[1], "video")

    def update_go(self):
        if not hasattr(self, "btn_go"):
            return
        busy = bool(getattr(self, "worker", None) and self.worker.isRunning())
        if busy:
            self.btn_go.setText(tr("转换中…"))
        elif self.sel:
            self.btn_go.setText(tr("开始转换") + " → " + (self.sel[4] or self.sel[1]))
        else:
            self.btn_go.setText(tr("请先选择格式"))
        self.btn_go.setEnabled(bool(self.sel) and not busy)

    def start_selected(self):
        if self.sel:
            _, fmt, kind, params, label = self.sel
            self.start(fmt, kind, params, label)

    # ---- 平滑进度
    def set_bar(self, frac):
        self.bar_anim.stop()
        self.bar_anim.setStartValue(self.bar.value())
        self.bar_anim.setEndValue(int(max(self.bar.value(), frac * 1000)))
        self.bar_anim.start()

    def creep(self):
        """单个文件处理期间，进度条向该文件的终点缓慢推进，不会卡住不动。"""
        if self.bar_anim.state() == QPropertyAnimation.State.Running:
            return
        lo, hi = self.prog
        target = (lo + (hi - lo) * 0.92) * 1000
        cur = self.bar.value()
        if cur < target:
            self.bar.setValue(int(cur + max(1, (target - cur) * 0.04)))

    def on_prog(self, i, text, n):
        self.prog = [i / n, (i + 1) / n]
        self.prog_lbl.setText(f"{i + 1}/{n}")
        self.status.setText(text)
        self.set_bar(i / n)

    # ---- 能力说明
    def show_cat(self, i):
        self.stack.setCurrentIndex(i)
        (self.cat_btns + [self.cat_preset])[i].setChecked(True)
        kind = self.cat_kinds[i]
        self.cap_hint.setText("ⓘ " + tr(CAPS[kind]))
        self.cap_hint.setToolTip(tr(CAPS_COMMON))
        for b in self.fmt_buttons:
            b.setToolTip(tr(CAPS.get(getattr(b, "kind", "preset"), "")))

    # ---- 预设
    def presets(self):
        return self.cfg.get("presets", [])

    def preset_by_id(self, pid):
        return next((p for p in self.presets() if p["id"] == pid), None)

    @staticmethod
    def preset_params(p):
        return {k: p.get(k) for k in ("quality", "max_side", "pages", "vcodec") if p.get(k)}

    @staticmethod
    def preset_desc(p):
        bits = [p["fmt"]]
        if p.get("quality"):
            bits.append(tr("质量 {q}%").format(q=p["quality"]))
        if p.get("max_side"):
            bits.append(tr("最长边 {n}px").format(n=p["max_side"]))
        if p.get("pages"):
            bits.append(tr("第 {p} 页").format(p=p["pages"]))
        if p.get("kind") == "video" and p.get("vcodec") not in (None, "", "auto"):
            bits.append(videoconv.codec_label(p["vcodec"]).split("（")[0])
        return " · ".join(bits)

    def rebuild_presets(self):
        g = self.preset_grid
        while g.count():
            w = g.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self.fmt_buttons = [b for b in self.fmt_buttons if getattr(b, "kind", None) != "preset"]
        if getattr(self, "sel", None) and self.sel[0] not in self.fmt_buttons:
            self.sel = None
            self.update_go()
        for k, p in enumerate(self.presets()):
            b = QPushButton(p["name"], objectName="fmt", checkable=True)
            b.setMinimumWidth(150)
            b.setMaximumWidth(260)
            b.setToolTip(self.preset_desc(p))
            b.kind = "preset"
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, b=b, p=p: self.select(b, p["fmt"], p["kind"], self.preset_params(p), p["name"]))
            g.addWidget(b, k // 4, k % 4)
            self.fmt_buttons.append(b)
        m = QPushButton()
        m.clicked.connect(self.open_presets)
        n = len(self.presets())
        g.addWidget(m, n // 4 + (1 if n % 4 else 0) if n else 0, 0)
        g.setRowStretch(g.rowCount(), 1)
        m.setText(tr("管理预设…"))
        m.setMaximumWidth(260)
        g.setColumnStretch(4, 1)
        busy = getattr(self, "worker", None) and self.worker.isRunning()
        for b in self.fmt_buttons:
            b.setEnabled(not busy)

    def open_presets(self):
        dlg = PresetDialog(self)
        if dlg.exec():
            self.cfg["presets"] = dlg.items
            ids = {p["id"] for p in dlg.items}
            self.cfg["ball_formats"] = [k for k in self.cfg.get("ball_formats", [])
                                        if not k.startswith("preset:") or k[7:] in ids]
            self.save()
            self.rebuild_presets()
            if self.ball:
                self.ball.rebuild()

    # ---- 任务管理（主窗口与悬浮球共用）
    def launch(self, files, fmt, kind, params=None, label=None, source="主窗口", on_done=None):
        w = Worker(files, self.out_root, fmt, kind, self.sec_cfg(), params)
        w.ask_dir.connect(lambda r, w=w: self.ask_out_dir(w, r))
        self.task_seq += 1
        task = {"id": self.task_seq, "source": source, "label": label or fmt, "fmt": fmt, "kind": kind,
                "params": params or {}, "files": list(files), "results": [None] * len(files), "worker": w,
                "state": "running", "limit": ""}
        self.tasks.append(task)
        self.jobs.append(w)

        def file_done(i, info):
            task["results"][i] = info
            self.refresh_tasks()

        def fin(ok, bad):
            w.wait()
            self.jobs.remove(w)
            task["state"] = "cancelled" if w.cancel_ev.is_set() else "done"
            task["limit"] = w.limit_problem
            self.after_job()
            done_rs = [r for r in task["results"] if r]
            self.add_results(done_rs)
            self.record_history(task, done_rs)
            self.archive_sources([r["src"] for r in done_rs if r["state"] not in ("failed", "cancelled")])
            self.refresh_tasks()
            if on_done:
                on_done(task, ok, bad)
        w.task = task
        w.file_done.connect(file_done)
        w.finished_all.connect(fin)
        w.start()
        self.refresh_tasks()
        return w

    def update_task_btn(self):
        n = sum(1 for t in self.tasks if t["state"] == "running")
        self.btn_tasks.badge = n
        self.btn_tasks.update()

    def refresh_tasks(self):
        self.update_task_btn()
        if self.task_dlg and self.task_dlg.isVisible():
            self.task_dlg.refresh()

    def open_tasks(self):
        if not self.task_dlg:
            self.task_dlg = TaskDialog(self)
        self.task_dlg.refresh()
        self.task_dlg.show()
        self.task_dlg.raise_()

    def cancel_task(self, task):
        if task["state"] == "running":
            task["worker"].cancel()

    def retry_task(self, task):
        failed = [r["src"] for r in task["results"] if r and r["state"] in ("failed", "cancelled")]
        failed += [f for f, r in zip(task["files"], task["results"]) if r is None and task["state"] != "running"]
        if failed:
            self.launch(failed, task["fmt"], task["kind"], task["params"], task["label"], tr("重试"))

    def ask_out_dir(self, worker, root):
        d = OutFailDialog(self, root).ask()
        worker.answer_dir(d)

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
            self.cfg["ball_formats"] = dlg.selected
            self.cfg["ball_auto_open"] = dlg.auto_open.isChecked()
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
        # 第一次点 ✕ 询问，之后按记住的选择：隐藏到系统托盘 / 完全退出
        choice = self.cfg.get("close_choice")
        if choice not in ("hide", "quit"):
            choice = CloseAsk(self).ask()
            if not choice:
                e.ignore()
                return
            self.cfg["close_choice"] = choice
            self.save()
        if choice == "hide":
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

    def run_job(self, files, fmt, kind, callback, auto_open=False, params=None, label=None):
        def fin(task, ok, bad):
            if auto_open and ok:
                os.startfile(os.path.dirname(ok[0]))
            self.report_limit(task)
            callback(task, ok, bad)
        return self.launch(files, fmt, kind, params, label, tr("悬浮球"), fin)

    def open_task(self, task):
        self.open_tasks()
        dlg = self.task_dlg
        for i in range(dlg.tree.topLevelItemCount()):
            it = dlg.tree.topLevelItem(i)
            if it.data(0, Qt.ItemDataRole.UserRole) == task["id"]:
                dlg.tree.setCurrentItem(it)
                it.setExpanded(True)

    def report_limit(self, task):
        if task["limit"]:
            self.tray.showMessage(tr("资源限制未生效"), tr("处理进程的内存 / 优先级限制没有成功应用：") + tr(task["limit"]),
                                  QIcon(os.path.join(ASSETS, "icon.ico")), 6000)

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

    EDGE = BORDER + 5      # 边缘可拖拽范围（含窗口外圈透明边距）
    CORNER = 18            # 角落范围更大，便于斜向缩放

    def _edges(self, pos: QPoint):
        if self.isMaximized() or self.isFullScreen():
            return Qt.Edge(0)
        x, y, w, h = pos.x(), pos.y(), self.width(), self.height()
        if not (0 <= x < w and 0 <= y < h):
            return Qt.Edge(0)
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        el, er, et, eb = x < self.EDGE, x >= w - self.EDGE, y < self.EDGE, y >= h - self.EDGE
        cl, cr, ct, cb = x < self.CORNER, x >= w - self.CORNER, y < self.CORNER, y >= h - self.CORNER
        if (el or et) and cl and ct: return L | T
        if (er or et) and cr and ct: return R | T
        if (el or eb) and cl and cb: return L | B
        if (er or eb) and cr and cb: return R | B
        e = Qt.Edge(0)
        if el: e |= L
        if er: e |= R
        if et: e |= T
        if eb: e |= B
        return e

    def paintEvent(self, e):
        # 外圈边距用几乎透明（alpha=1）的颜色填充：完全透明的像素在 Windows 上会被鼠标穿透，边缘就抓不住
        if not self.isMaximized():
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(0, 0, 0, 1))

    @staticmethod
    def _shape(e):
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if e in (L | T, R | B):
            return Qt.CursorShape.SizeFDiagCursor
        if e in (R | T, L | B):
            return Qt.CursorShape.SizeBDiagCursor
        if e in (L, R):
            return Qt.CursorShape.SizeHorCursor
        if e in (T, B):
            return Qt.CursorShape.SizeVerCursor
        return None

    def poll_edges(self):
        """子控件会挡住窗口边缘的鼠标事件，所以按鼠标位置统一判断，边缘与角落都能稳定触发。"""
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return
        shape = None
        if self.isVisible():
            under = QApplication.widgetAt(QCursor.pos())
            if under is not None and under.window() is self:
                shape = self._shape(self._edges(self.mapFromGlobal(QCursor.pos())))
        if shape != self._ov_cursor:
            if self._ov_cursor is not None:
                QApplication.restoreOverrideCursor()
            if shape is not None:
                QApplication.setOverrideCursor(QCursor(shape))
            self._ov_cursor = shape

    def eventFilter(self, obj, ev):
        if ev.type() == ev.Type.Polish and isinstance(obj, QWidget):
            if obj.isWindow():
                round_popup(obj)
            elif isinstance(obj, (QPushButton, QCheckBox, QRadioButton, QComboBox)):
                obj.setCursor(Qt.CursorShape.PointingHandCursor)
        if (ev.type() == ev.Type.MouseButtonPress and isinstance(obj, QWidget) and obj.window() is self
                and ev.button() == Qt.MouseButton.LeftButton):
            e = self._edges(self.mapFromGlobal(ev.globalPosition().toPoint()))
            if e:
                self.windowHandle().startSystemResize(e)
                return True
        return False

    # ---- 输出目录
    def update_dir_label(self):
        self.btn_locate.setToolTip(tr("选中结果时在文件夹中定位；未选中时打开输出文件夹：") +
                                   f"\n{self.out_root}\\{time.strftime('%Y-%m-%d')}")
        self.sync_warn.setText(tr("⚠ 输出目录位于云同步文件夹中，转换结果可能会被自动上传。") if synced_dir(self.out_root) else "")
        self.sync_warn.setVisible(synced_dir(self.out_root))

    def locate(self):
        ps = self.selected_results(need=False)
        show_in_folder(ps) if ps else self.open_out()

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
    def thumb(self, p):
        """缩略图按小尺寸解码，避免整张大图读进内存。"""
        rd = QImageReader(p)
        sz = rd.size()
        if sz.isValid() and sz.width() > 0:
            sz.scale(56, 56, Qt.AspectRatioMode.KeepAspectRatio)
            rd.setScaledSize(sz)
        img = rd.read()
        return QIcon(QPixmap.fromImage(img)) if not img.isNull() else None

    def add_results(self, infos):
        added = False
        for info in infos:
            st = info["state"]
            if st == "cancelled":
                continue
            if st == "failed":
                it = QListWidgetItem(self.icons.icon(QFileIconProvider.IconType.File),
                                     f"{os.path.basename(info['src'])}   ·  {tr('失败')}")
                it.setForeground(QBrush(QColor(LEVEL_COLOR["failed"])))
                it.setToolTip(info["src"] + "\n" + info["error"])
                it.setData(Qt.ItemDataRole.UserRole, None)
                self.results.insertItem(0, it)
                added = True
                continue
            for p in info["files"]:
                ext = os.path.splitext(p)[1][1:].lower()
                icon = (self.thumb(p) if ext in IMG_EXT else None) or self.icons.icon(QFileInfo(p))
                meta = info["meta"].get(p, "unsupported")
                self.result_info[p] = {"level": st, "meta": meta, "notes": info["notes"]}
                tag = tr(LEVEL_TEXT[st]) + ("" if meta == "clean" else " · ⚠ " + tr(META_TEXT[meta]))
                it = QListWidgetItem(icon, f"{os.path.basename(p)}   ·  {tag}")
                it.setForeground(QBrush(QColor(LEVEL_COLOR[st])))
                it.setData(Qt.ItemDataRole.UserRole, p)
                it.setToolTip("\n".join([p, tr(LEVEL_TEXT[st]), tr(META_TEXT[meta])] + [tr(n) for n in info["notes"]]))
                self.results.insertItem(0, it)
                it.setSelected(True)
                added = True
        if added:
            self.results.scrollToTop()

    def record_history(self, task, infos):
        now = time.time()
        entries = [{"t": now, "src": r["src"], "files": r.get("files", []), "state": r["state"], "fmt": task["fmt"],
                    "via": task["source"], "error": r.get("error", "")}
                   for r in infos if r["state"] != "cancelled"]
        if entries:
            try:
                add_history(entries, self.sec("history_days"))
            except OSError:
                pass

    def archive_sources(self, srcs):
        """转换完成的源文件移出输入列表，可在「历史」中查看。"""
        done = set(os.path.normcase(x) for x in srcs)
        for i in range(self.list.count() - 1, -1, -1):
            it = self.list.item(i)
            pth = it.data(Qt.ItemDataRole.UserRole) or it.text()
            if os.path.normcase(str(pth)) in done:
                self.list.takeItem(i)

    def archive_results(self, paths):
        """打开过的结果移出结果列表（归档到历史记录）。"""
        ps = set(paths)
        for i in range(self.results.count() - 1, -1, -1):
            if self.results.item(i).data(Qt.ItemDataRole.UserRole) in ps:
                self.results.takeItem(i)

    def open_result(self, p):
        if p and os.path.exists(p):
            os.startfile(p)
            self.archive_results([p])

    def open_history(self):
        HistoryDialog(self).exec()

    def selected_results(self, need=True):
        ps = [it.data(Qt.ItemDataRole.UserRole) for it in self.results.selectedItems()]
        ps = [p for p in ps if p and os.path.exists(p)]
        if not ps and need:
            self.status.setText(tr("请先选择结果文件"))
        return ps

    def open_selected(self):
        ps = self.selected_results()[:20]
        for p in ps:
            os.startfile(p)
        self.archive_results(ps)

    def results_menu(self, pos):
        if not self.results.itemAt(pos):
            return
        m = QMenu(self)
        m.addAction(tr("打开"), self.open_selected)
        m.addAction(tr("定位"), self.locate)
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

    def confirm_share(self, action, ps, extra=""):
        if not self.sec("share_confirm"):
            return True
        items, need = [], 0
        for p in ps:
            inf = self.result_info.get(p)
            warn = []
            if not inf:
                warn.append(tr("不是本次生成的结果，元数据状态未知"))
            else:
                if inf["meta"] != "clean":
                    warn.append(tr(META_TEXT[inf["meta"]]))
                if inf["level"] != "full":
                    warn.append(tr(LEVEL_TEXT[inf["level"]]))
            need += bool(warn)
            items.append(os.path.basename(p) + (f"   ⚠ {'，'.join(warn)}" if warn else ""))
        note = tr("请确认文件名、正文与图片内容可以分享。")
        if need:
            note = tr("{n} 个文件需要人工检查（见 ⚠ 标记）。").format(n=need) + note
        return ConfirmDialog(self, "确认分享", tr(action) + "\n" + tr("共 {n} 个文件：").format(n=len(ps)),
                             items, extra, note).ask()

    def zip_path(self, ps):
        base = os.path.join(os.path.dirname(ps[0]), time.strftime("分享_%H%M%S"))
        zp, i = base + ".zip", 1
        while os.path.exists(zp):
            i += 1
            zp = f"{base}_{i}.zip"
        return zp

    def share_windows(self):
        ps = self.selected_results()
        if not ps:
            return
        if len(ps) > 1:
            zp = self.zip_path(ps)
            if not self.confirm_share("将打包为一个 ZIP 后打开 Windows 共享。", ps, tr("ZIP 保存位置：") + zp):
                return
            p = self.share_zip(locate=False, ps=ps, zp=zp)
            self.status.setText(tr("多个文件已打包为 ZIP 再共享") + "：" + p)
        else:
            if not self.confirm_share("将打开 Windows 共享面板。", ps):
                return
            p = ps[0]
        windows_share(p)

    def share_copy(self):
        ps = self.selected_results()
        if ps:
            md = QMimeData()
            md.setUrls([QUrl.fromLocalFile(p) for p in ps])
            QApplication.clipboard().setMimeData(private_mime(md))
            self.status.setText(tr("已复制 {n} 个文件，可直接粘贴发送").format(n=len(ps)))

    def share_paths(self):
        ps = self.selected_results()
        if ps and self.confirm_share("将把完整路径复制到剪贴板（不进入剪贴板历史）。", ps):
            md = QMimeData()
            md.setText("\n".join(ps))
            QApplication.clipboard().setMimeData(private_mime(md))
            self.status.setText(tr("已复制路径"))

    def share_zip(self, locate=True, ps=None, zp=None):
        if ps is None:
            ps = self.selected_results()
            if not ps:
                return None
            zp = self.zip_path(ps)
            if not self.confirm_share("将把这些文件打包为 ZIP。", ps, tr("ZIP 保存位置：") + zp):
                return None
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for p in ps:
                z.write(p, os.path.basename(p))
        safejob.record([zp])
        self.status.setText(tr("已打包：{p}").format(p=zp))
        if locate:
            show_in_folder([zp])
        return zp

    # ---- 转换
    def start(self, fmt, kind, params=None, label=None):
        files = self.files()
        if not files:
            self.status.setText(tr("请先拖入或添加文件"))
            return
        self.results.clearSelection()
        n = len(files)
        self.bar_anim.stop()
        self.bar.setValue(0)
        self.prog = [0.0, 1 / n]
        self.prog_lbl.setText(f"0/{n}")
        self.prog_box.show()
        self.prog_timer.start()
        self.worker = self.launch(files, fmt, kind, params, label, tr("主窗口"), self.done)
        self.worker.progress.connect(lambda i, t: self.on_prog(i, t, n))
        self.worker.file_done.connect(lambda i, _: (setattr(self, "prog", [(i + 1) / n, (i + 1) / n]),
                                                    self.set_bar((i + 1) / n)))
        self.update_go()

    def done(self, task, ok, bad):
        self.prog_timer.stop()
        self.set_bar(1.0)
        n = len(task["files"])
        self.prog_lbl.setText(f"{n}/{n}")
        QTimer.singleShot(1500, lambda: self.prog_box.hide() if not self.worker.isRunning() else None)
        self.update_go()
        rs = [r for r in task["results"] if r]
        cnt = {k: sum(1 for r in rs if r["state"] == k) for k in ("full", "partial", "preview", "failed", "cancelled")}
        msg = tr("完成：生成 {n} 个文件").format(n=len(ok))
        msg += "　" + "　".join(f"<span style='color:{LEVEL_COLOR[k]}'>{tr(LEVEL_TEXT[k])} {v}</span>"
                               for k, v in cnt.items() if v)
        if ok:
            msg += (f'　<a href="{QUrl.fromLocalFile(os.path.dirname(ok[0])).toString()}" '
                    f'style="color:#4ea1ff">{tr("打开所在文件夹")}</a>')
        if self.worker.redirect:
            msg += "<br><span style='color:#e3b341'>" + tr("本次已改存到：") + self.worker.redirect + "</span>"
        if self.worker.blocked:
            msg += "<br><span style='color:#e3b341'>" + tr("blocked").format(d=FALLBACK_OUT) + "</span>"
        if task["limit"]:
            msg += "<br><span style='color:#e3b341'>⚠ " + tr("资源限制未生效") + "：" + tr(task["limit"]) + "</span>"
        if bad:
            msg += "<br><span style='color:#ff7b72'>" + tr("失败：") + "<br>".join(bad[:5]) + \
                   ("<br>…" if len(bad) > 5 else "") + "</span>"
        self.status.setText(msg)
        self.update_dir_label()


def round_popup(w):
    """菜单、下拉列表与提示框是独立的方形窗口，背景会露出直角；改为透明背景，只显示样式表画的圆角。"""
    cls = w.metaObject().className()
    if cls in ("QMenu", "QComboBoxPrivateContainer", "QTipLabel") and not w.property("rounded"):
        w.setProperty("rounded", True)
        w.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        w.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if cls == "QComboBoxPrivateContainer":
            w.setStyleSheet("QComboBoxPrivateContainer{background:transparent;border:none}")


def main_of(w):
    """沿父级找到主窗口。"""
    while w is not None and not isinstance(w, Main):
        w = w.parent()
    return w


class StyledDialog(QFrame):
    """应用内页面：在主窗口里替换主页显示，顶部带「返回」；exec() 等待返回结果，用法与对话框相同。
    overlay=True 时作为浮动卡片叠在主页上（用于新手引导，需要同时看到被介绍的模块）。"""
    def __init__(self, parent, title_key, lang_btn=False, accent=False, overlay=False):
        self.main = main_of(parent)
        super().__init__(self.main, objectName="pageCard" if overlay else "page")
        self.title_key = title_key
        self.overlay = overlay
        self.keep = False   # True：返回后保留页面（任务页会反复打开）
        self._result, self._loop, self._shown = 0, None, False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QWidget(objectName="pageHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(12 if not overlay else 16, 8, 12, 8)
        hl.setSpacing(10)
        self.btn_back = QPushButton(objectName="back")
        self.btn_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_back.clicked.connect(self.reject)
        if not overlay:
            hl.addWidget(self.btn_back)
            self.btn_back.hide()   # 左侧常驻菜单栏负责导航，不再显示返回按钮
        self.title_lbl = QLabel(objectName="pageTitle")
        hl.addWidget(self.title_lbl)
        hl.addStretch()
        self.btn_lang = None
        if lang_btn:
            self.btn_lang = QPushButton(objectName="tool")
            self.btn_lang.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            hl.addWidget(self.btn_lang)
        outer.addWidget(head)
        body = QWidget(objectName="pageBody")
        if overlay:
            outer.addWidget(body, 1)
        else:
            line = QFrame(objectName="pageSep")
            line.setFixedHeight(1)
            outer.addWidget(line)
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.Shape.NoFrame)
            holder = QWidget(objectName="pageBody")
            self._vbox = QVBoxLayout(holder)
            self._vbox.setContentsMargins(0, 0, 0, 0)
            hh = QHBoxLayout()
            hh.addStretch(1)
            body.setMaximumWidth(860)
            hh.addWidget(body, 30)
            hh.addStretch(1)
            self._vbox.addStretch(0)
            self._vbox.addLayout(hh, 1)
            self._vbox.addStretch(0)
            self.body = body
            sc.setWidget(holder)
            outer.addWidget(sc, 1)
        self.content = QVBoxLayout(body)
        self.content.setContentsMargins(20, 14, 20, 16)
        self.titlebar = self   # 兼容旧代码：self.titlebar.btn_lang
        self.hide()
        self.retitle()

    def retitle(self):
        self.title_lbl.setText(tr(self.title_key))
        self.btn_back.setText("←  " + tr("返回"))
        if self.btn_lang:
            self.btn_lang.setText("EN" if LANG == "zh" else "中文")
            self.btn_lang.setToolTip(tr("切换语言"))

    def compact(self, width=560):
        """内容较少的页面（确认、询问）：居中显示为一张卡片，而不是铺满整个窗口。"""
        self.body.setObjectName("panel")
        self.body.setMaximumWidth(width)
        self.body.setMinimumWidth(min(width, 420))
        self._vbox.setStretch(0, 1)
        self._vbox.setStretch(1, 0)
        self._vbox.setStretch(2, 2)

    # 页面尺寸由主窗口决定，忽略对话框式的尺寸设置，避免窗口忽大忽小
    def resize(self, *a): pass
    def setFixedWidth(self, *a): pass
    def setMinimumWidth(self, *a): pass
    def setWindowModality(self, *a): pass
    def setWindowTitle(self, *a): pass
    def move(self, *a):
        if self.overlay:
            super().move(*a)

    def adjustSize(self):
        if self.overlay:
            self.setFixedWidth_(430)
            super().adjustSize()

    def setFixedWidth_(self, w):
        QFrame.setFixedWidth(self, w)

    def show(self):
        if self._shown:
            self.raise_()
            return
        self._shown = True
        self.main.push_page(self)

    def hide(self):
        if getattr(self, "_shown", False):
            self._shown = False
            self.main.pop_page(self)
        else:
            super().hide()

    def isVisible(self):
        return self._shown

    def show_(self):
        QFrame.show(self)

    def done(self, r):
        self._result = r
        self.hide()
        if self._loop:
            self._loop.quit()

    def accept(self):
        self.done(1)

    def reject(self):
        self.done(0)

    def exec(self):
        from PyQt6.QtCore import QEventLoop
        self._result = 0
        self.show()
        self._loop = QEventLoop()
        self._loop.exec()
        self._loop = None
        return self._result

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(e)


class SideButton(QPushButton):
    """左侧导航项：自绘图标（Segoe Fluent Icons）+ 文字；折叠时只画图标。"""
    def __init__(self, glyph, key):
        super().__init__(objectName="sideBtn")
        self.glyph, self.key, self.expanded, self.badge = glyph, key, True, 0
        self.setFixedHeight(38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        col = QColor(C("softt") if on else (C("text") if self.underMouse() else C("muted")))
        f = QFont("Segoe Fluent Icons")
        f.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
        f.setPixelSize(16)
        p.setFont(f)
        p.setPen(col)
        ind = 16 if getattr(self, "child", False) and self.expanded else 0
        if getattr(self, "child", False):
            p.setPen(QPen(QColor(C("btnb")), 1.5))
            if self.expanded:
                p.drawLine(QPointF(19, -6), QPointF(19, self.height() / 2))
                p.drawLine(QPointF(19, self.height() / 2), QPointF(28, self.height() / 2))
            else:
                p.drawLine(QPointF(19, -6), QPointF(19, 4))
            f.setPixelSize(14)
            p.setFont(f)
            p.setPen(col)
        icon_r = QRectF(ind + (8 if ind else 0), 0, 38, self.height())
        p.drawText(icon_r, Qt.AlignmentFlag.AlignCenter, self.glyph)
        if getattr(self, "is_switch", False):   # 悬浮球：画一个开关，清楚表示开 / 关
            on = self.isChecked()
            if self.expanded:
                tr_ = QRectF(self.width() - 44, (self.height() - 18) / 2, 34, 18)
            else:
                tr_ = QRectF(24, self.height() - 13, 14, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C("accent") if on else C("btnb")))
            p.drawRoundedRect(tr_, tr_.height() / 2, tr_.height() / 2)
            d = tr_.height() - 4
            x = tr_.right() - d - 2 if on else tr_.left() + 2
            p.setBrush(QColor("white"))
            p.drawEllipse(QRectF(x, tr_.top() + 2, d, d))
        if self.badge:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(C("accent")))
            p.drawEllipse(QRectF(24, 7, 9, 9))
        if self.expanded:
            f2 = self.font()
            f2.setPixelSize(13)
            p.setFont(f2)
            p.setPen(col)
            txt = tr(self.key) + (f"  ({self.badge})" if self.badge else "")
            x0 = 40 + ind + (8 if ind else 0)
            room = self.width() - x0 - (52 if getattr(self, "is_switch", False) else 8)   # 给开关留位置
            if p.fontMetrics().horizontalAdvance(txt) > room:
                self.setToolTip(tr(self.key))
            txt = p.fontMetrics().elidedText(txt, Qt.TextElideMode.ElideRight, int(room))
            p.drawText(QRectF(x0, 0, room, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, txt)


class NavButton(QPushButton):
    """左对齐文字 + 右侧绘制的数量徽标（选中时徽标变为主题色）。"""
    def __init__(self, count=None):
        super().__init__(objectName="navBtn")
        self.count = count

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = self.font()
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        txt = str(self.count)
        w = max(22, p.fontMetrics().horizontalAdvance(txt) + 12)
        h = 18
        r = QRectF(self.width() - w - 10, (self.height() - h) / 2, w, h)
        on = self.isChecked()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C("accent") if on else C("area")))
        p.drawRoundedRect(r, h / 2, h / 2)
        p.setPen(QColor("white" if on else C("muted")))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, txt)


class Switch(QCheckBox):
    """滑块开关。"""
    def __init__(self, small=False):
        super().__init__()
        self.setFixedSize(*((34, 18) if small else (40, 22)))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._x = 0.0
        self.anim = QPropertyAnimation(self, b"knob", self)
        self.anim.setDuration(140)
        self.toggled.connect(self._go)

    def _go(self, on):
        self.anim.stop()
        self.anim.setStartValue(self._x)
        self.anim.setEndValue(1.0 if on else 0.0)
        self.anim.start()

    def get_knob(self):
        return self._x

    def set_knob(self, v):
        self._x = v
        self.update()

    knob = pyqtProperty(float, get_knob, set_knob)

    def setChecked(self, on):
        """程序设置的初始状态直接到位，不播放动画。"""
        super().setChecked(on)
        self.anim.stop()
        self._x = 1.0 if on else 0.0
        self.update()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        off, on = QColor(C("knob_off")), QColor(C("accent"))
        t = self._x
        p.setBrush(QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                          int(off.blue() + (on.blue() - off.blue()) * t)))
        h = self.height()
        p.drawRoundedRect(self.rect(), h / 2, h / 2)
        p.setBrush(QColor("white"))
        d = h - 6
        p.drawEllipse(int(3 + t * (self.width() - d - 6)), 3, d, d)


class CloseAsk(StyledDialog):
    """第一次点 ✕ 时询问关闭方式。"""
    def __init__(self, main):
        super().__init__(main, "关闭格式转换器")
        self.compact()
        self.choice = None
        v = self.content
        v.setContentsMargins(22, 10, 22, 16)
        v.addWidget(QLabel(tr("点击 ✕ 关闭窗口时，你希望：")))
        v.addWidget(QLabel(tr("此选择会被记住，之后可在主页「设置」中修改。"), objectName="hint"))
        h = QHBoxLayout()
        h.addStretch()
        for key, text, obj in (("quit", "完全退出", ""), ("hide", "隐藏到系统托盘", "primary")):
            b = QPushButton(tr(text), objectName=obj)
            b.clicked.connect(lambda _, k=key: (setattr(self, "choice", k), self.accept()))
            h.addWidget(b)
        v.addSpacing(8)
        v.addLayout(h)

    def ask(self):
        self.exec()
        return self.choice


class ConfirmDialog(StyledDialog):
    """通用确认框：说明 + 文件名列表 + 附加信息。"""
    def __init__(self, main, title, msg, items=(), extra="", note="", ok_text="继续"):
        super().__init__(main, title)
        self.compact()
        self.setMinimumWidth(440)
        v = self.content
        v.setContentsMargins(22, 10, 22, 16)
        lb = QLabel(msg)
        lb.setWordWrap(True)
        v.addWidget(lb)
        if items:
            shown = list(items[:10]) + ([tr("…等 {n} 个").format(n=len(items))] if len(items) > 10 else [])
            box = QLabel("\n".join("• " + x for x in shown))
            box.setObjectName("box")
            box.setWordWrap(True)
            v.addWidget(box)
        for t, obj in ((extra, "hint"), (note, "warn")):
            if t:
                x = QLabel(t, objectName=obj)
                x.setWordWrap(True)
                x.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                v.addWidget(x)
        h = QHBoxLayout()
        h.addStretch()
        c = QPushButton(tr("取消"))
        c.clicked.connect(self.reject)
        ok = QPushButton(tr(ok_text), objectName="primary")
        ok.clicked.connect(self.accept)
        h.addWidget(c)
        h.addWidget(ok)
        v.addSpacing(6)
        v.addLayout(h)

    def ask(self):
        return bool(self.exec())


class OutFailDialog(StyledDialog):
    """输出目录写不进时暂停，让用户选择。"""
    def __init__(self, main, root):
        super().__init__(main, "输出目录无法写入")
        self.compact()
        self.main, self.result_dir = main, None
        self.setMinimumWidth(460)
        v = self.content
        v.setContentsMargins(22, 10, 22, 16)
        lb = QLabel(tr("无法写入：") + root + "\n" + tr("可能没有权限，或被 Windows「受控文件夹访问」拦截（该保护会保持开启）。"))
        lb.setWordWrap(True)
        v.addWidget(lb)
        h = QHBoxLayout()
        h.addStretch()
        for text, fn, obj in (("取消本次转换", self.reject, ""), ("存到「下载」", self.use_downloads, ""),
                              ("选择其他目录…", self.pick, "primary")):
            b = QPushButton(tr(text), objectName=obj)
            b.clicked.connect(fn)
            h.addWidget(b)
        v.addSpacing(8)
        v.addLayout(h)

    def use_downloads(self):
        self.result_dir = FALLBACK_OUT
        self.accept()

    def pick(self):
        d = QFileDialog.getExistingDirectory(self, tr("选择输出根目录（会按日期建子文件夹）"), os.path.expanduser("~"))
        if d:
            self.result_dir = os.path.normpath(d)
            self.accept()

    def ask(self):
        self.main.show_main()
        self.exec()
        return self.result_dir


class UnsavedDialog(QWidget):
    """设置未保存时的确认：覆盖在当前页面上的弹窗，背景虚化。返回 1 保存 / 2 不保存 / 0 继续编辑。"""
    def __init__(self, main):
        super().__init__(main.frame)
        self.main, self._result, self._loop = main, 0, None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card = QFrame(self, objectName="card")
        card.setFixedWidth(420)
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(12)
        v.addWidget(QLabel(tr("未保存的修改"), objectName="cardTitle"))
        lb = QLabel(tr("设置已修改但尚未保存，是否保存后再退出？"))
        lb.setWordWrap(True)
        v.addWidget(lb)
        h = QHBoxLayout()
        h.addStretch()
        for text, r, obj in (("继续编辑", 0, None), ("不保存", 2, None), ("保存", 1, "primary")):
            b = QPushButton(tr(text), objectName=obj) if obj else QPushButton(tr(text))
            b.clicked.connect(lambda _, r=r: self.done(r))
            h.addWidget(b)
        v.addLayout(h)
        lay = QVBoxLayout(self)
        lay.addWidget(card, 0, Qt.AlignmentFlag.AlignCenter)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(QRectF(self.rect()), 10, 10)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.done(0)

    def done(self, r):
        self._result = r
        if self._loop:
            self._loop.quit()

    def exec(self):
        from PyQt6.QtCore import QEventLoop
        from PyQt6.QtWidgets import QGraphicsBlurEffect
        blurred = [w for w in (self.main.pages, getattr(self.main, "side", None), self.main.title) if w]
        for w in blurred:
            fx = QGraphicsBlurEffect()
            fx.setBlurRadius(8)
            w.setGraphicsEffect(fx)
        self.setGeometry(self.main.frame.rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._loop = QEventLoop()
        self._loop.exec()
        self._loop = None
        for w in blurred:
            w.setGraphicsEffect(None)
        self.hide()
        self.deleteLater()
        return self._result


class SettingsDialog(StyledDialog):
    SWITCHES = (("ask_on_fail", "输出失败时询问", "写入失败时暂停，让你选择新目录、存到「下载」或取消，而不是自动改存。"),
                ("share_confirm", "分享前确认", "打开 Windows 共享、打包 ZIP 或复制完整路径前，列出文件数量和名称；复制的内容不进入剪贴板历史和跨设备同步。"),
                ("strip_meta", "移除敏感元数据", "去掉输出文件中的 GPS / EXIF、作者、修改者等信息（图片、Office 文档、PDF）。关闭后图片会保留原 EXIF。"),
                ("clean_temp", "自动清理临时文件", "每次转换结束（成功、失败或中止）后删除本程序产生的中间文件。"),
                ("isolate", "隔离进程处理", "在独立的低优先级子进程中解析文件，限制内存占用，超时会被强制中止，不影响主程序。"))
    NUMS = (("timeout_s", "单个文件处理超时（秒）", 10, 3600), ("mem_mb", "处理进程内存上限（MB）", 256, 32768),
            ("max_mb", "文件大小上限（MB）", 1, 20480), ("max_mpix", "图像像素上限（百万像素）", 1, 5000),
            ("max_unzip_mb", "压缩包解压后体积上限（MB）", 10, 51200))
    DAYS = (0, 1, 3, 7, 14, 30, 90)

    def __init__(self, main):
        super().__init__(main, "设置")
        self.main = main
        self.out_root = main.out_root
        # 左侧分类导航 + 右侧内容，每次只显示一类，避免长页面滚动
        wrap = QHBoxLayout()
        wrap.setSpacing(12)
        self.nav = QFrame(objectName="cats")
        self.nav.setFixedWidth(176)
        self.nav_l = QVBoxLayout(self.nav)
        self.nav_l.setContentsMargins(6, 6, 6, 6)
        self.nav_l.setSpacing(2)
        self.sec_stack = QStackedWidget()
        wrap.addWidget(self.nav, 0, Qt.AlignmentFlag.AlignTop)
        wrap.addWidget(self.sec_stack, 1)
        self.content.addLayout(wrap, 1)
        v = None

        # 常规
        c, cv = self.section(v, "常规")
        cv.addWidget(QLabel(tr("点击 ✕ 关闭主窗口时：")))
        self.rb_quit = QRadioButton(tr("完全退出"))
        self.rb_hide = QRadioButton(tr("隐藏到系统托盘（悬浮球与托盘继续可用）"))
        (self.rb_hide if main.cfg.get("close_choice") == "hide" else self.rb_quit).setChecked(True)
        cv.addWidget(self.rb_quit)
        cv.addWidget(self.rb_hide)
        cv.addSpacing(6)
        cv.addWidget(QLabel(tr("输出目录（按日期自动建子文件夹）：")))
        self.dir_lb = QLabel(objectName="hint")
        self.dir_lb.setWordWrap(True)
        cv.addWidget(self.dir_lb)
        self.dir_warn = QLabel(objectName="warn")
        self.dir_warn.setWordWrap(True)
        cv.addWidget(self.dir_warn)
        h = QHBoxLayout()
        for text, fn in (("更改输出目录…", self.pick_dir), ("打开输出文件夹", main.open_out)):
            b = QPushButton(tr(text))
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch()
        cv.addLayout(h)
        self.refresh_dir()
        cv.addStretch()

        # 外观：颜色预设
        c, cv = self.section(v, "外观")
        self.pal = {"bg": PALETTE["bg"], "accent": PALETTE["accent"]}
        self.swatches = {"bg": {}, "accent": {}}
        for kind, label, presets in (("bg", "背景色调", BG_PRESETS), ("accent", "按键高光色", ACCENT_PRESETS)):
            cv.addWidget(QLabel(tr(label)))
            row = QHBoxLayout()
            row.setSpacing(10)
            for key, name, col in presets:
                box = QVBoxLayout()
                box.setSpacing(4)
                b = QPushButton(objectName="swatch", checkable=True)
                b.setFixedSize(34, 34)
                shown = col or (BASE_THEMES["dark"]["card"] if THEME == "dark" else BASE_THEMES["light"]["card"])
                b.setStyleSheet(f"QPushButton#swatch{{background:{shown};border:2px solid {C('btnb')};border-radius:17px;}}"
                                f"QPushButton#swatch:hover{{border-color:{C('text')};}}"
                                f"QPushButton#swatch:checked{{border:3px solid {C('text')};}}")
                b.setChecked(self.pal[kind] == key)
                b.clicked.connect(lambda _, kind=kind, key=key: self.pick_palette(kind, key))
                box.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
                lb = QLabel(tr(name), objectName="hint")
                lb.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                box.addWidget(lb)
                row.addLayout(box)
                self.swatches[kind][key] = b
            row.addStretch()
            cv.addLayout(row)
            cv.addSpacing(6)
        ph = QLabel(tr("点击即可预览；保存设置后生效，不保存则恢复原来的颜色。深色 / 浅色模式都会套用。"), objectName="hint")
        ph.setWordWrap(True)
        cv.addWidget(ph)
        cv.addStretch()

        # 安全
        c, cv = self.section(v, "安全")
        self.sw = {}
        for key, title, desc in self.SWITCHES:
            row = QHBoxLayout()
            sw = Switch()
            sw.setChecked(bool(main.sec(key)))
            self.sw[key] = sw
            row.addWidget(sw, 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(QLabel(tr(title)))
            d = QLabel(tr(desc), objectName="hint")
            d.setWordWrap(True)
            col.addWidget(d)
            row.addLayout(col, 1)
            cv.addLayout(row)
        hr = QHBoxLayout()
        hr.addWidget(QLabel(tr("历史记录保留时间")))
        self.hist = QComboBox()
        for d in HISTORY_DAYS:
            self.hist.addItem(tr("{d} 天").format(d=d), d)
        hd = main.sec("history_days")
        self.hist.setCurrentIndex(HISTORY_DAYS.index(hd) if hd in HISTORY_DAYS else 1)
        hr.addWidget(self.hist)
        hr.addStretch()
        cv.addLayout(hr)
        d = QLabel(tr("「历史」页只显示这段时间内的转换记录，更早的记录会被清除（只删记录，不删文件）。"), objectName="hint")
        d.setWordWrap(True)
        cv.addWidget(d)
        cv.addStretch()
        c, cv = self.section(v, "资源与清理")
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        self.num = {}
        for i, (key, title, lo, hi) in enumerate(self.NUMS):
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.setValue(int(main.sec(key)))
            self.num[key] = sp
            g.addWidget(QLabel(tr(title)), i, 0)
            g.addWidget(sp, i, 1)
        self.days = QComboBox()
        for d in self.DAYS:
            self.days.addItem(tr("关闭") if d == 0 else tr("{d} 天后").format(d=d), d)
        self.days.setCurrentIndex(max(0, self.DAYS.index(main.sec("auto_delete_days"))
                                      if main.sec("auto_delete_days") in self.DAYS else 0))
        g.addWidget(QLabel(tr("定时删除生成文件")), len(self.NUMS), 0)
        g.addWidget(self.days, len(self.NUMS), 1)
        g.setColumnStretch(2, 1)
        cv.addLayout(g)
        d = QLabel(tr("定时删除只处理本程序生成并记录在清单中的文件；你放进去的文件或生成后被修改过的文件不会删除。到期文件移到回收站，可以还原。"), objectName="hint")
        d.setWordWrap(True)
        cv.addWidget(d)
        h = QHBoxLayout()
        b = QPushButton(tr("立即清理临时文件"))
        b.clicked.connect(self.clean_now)
        h.addWidget(b)
        self.clean_lb = QLabel(objectName="hint")
        h.addWidget(self.clean_lb, 1)
        cv.addLayout(h)
        d = QLabel(tr("始终开启：原文件只读不修改；结果先写入暂存文件夹，完成后再发布，同名自动编号，主窗口与悬浮球同时转换也不会互相覆盖；"
                      "表格输出防公式注入（以 = + - @ 开头的文本按纯文本写入，负数仍是数字）。"), objectName="hint")
        d.setWordWrap(True)
        cv.addWidget(d)

        # 关于
        c, cv = self.section(v, "关于")
        for t in (f"{tr('格式转换器')}  v{VERSION}", tr("配置文件：") + CONFIG, tr("临时文件：") + safejob.TMP_ROOT,
                  "github.com/RonganBai/Universal-File-Format-Converter"):
            x = QLabel(t, objectName="hint" if not t.startswith(tr("格式转换器")) else "cardTitle")
            x.setWordWrap(True)
            x.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            cv.addWidget(x)
        cv.addStretch()
        self.nav_l.addStretch()
        self.show_sec(0)

        h = QHBoxLayout()
        h.addStretch()
        c = QPushButton(tr("取消"))
        c.clicked.connect(self.reject)
        ok = QPushButton(tr("确定"), objectName="primary")
        ok.clicked.connect(self.accept)
        h.addWidget(c)
        h.addWidget(ok)
        self.content.addLayout(h)

    def section(self, v, title):
        f = QFrame(objectName="panel")
        cv = QVBoxLayout(f)
        cv.setContentsMargins(18, 14, 18, 14)
        cv.setSpacing(10)
        cv.addWidget(QLabel(tr(title), objectName="cardTitle"))
        i = self.sec_stack.count()
        self.sec_stack.addWidget(f)
        b = QPushButton(tr(title).replace("&", "&&"), checkable=True, autoExclusive=True)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.clicked.connect(lambda _, i=i: self.show_sec(i))
        self.nav_l.addWidget(b)
        return f, cv

    def show_sec(self, i):
        self.sec_stack.setCurrentIndex(i)
        self.nav_l.itemAt(i).widget().setChecked(True)

    def refresh_dir(self):
        self.dir_lb.setText(self.out_root)
        self.dir_warn.setText(tr("⚠ 该目录位于云同步文件夹中，转换结果可能会被自动上传。"))
        self.dir_warn.setVisible(synced_dir(self.out_root))

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("选择输出根目录（会按日期建子文件夹）"), self.out_root)
        if d:
            self.out_root = os.path.normpath(d)
            self.refresh_dir()

    def clean_now(self):
        busy = self.main.jobs or (getattr(self.main, "worker", None) and self.main.worker.isRunning())
        if busy:
            self.clean_lb.setText(tr("有任务正在转换，请稍后再试"))
            return
        n = safejob.clean_temp(self.main.out_root)
        self.clean_lb.setText(tr("已清理 {n} 项").format(n=n))

    def accept(self):
        days = self.days.currentData()
        if days and days != self.main.sec("auto_delete_days"):
            ds = safejob.expired_items(days)
            total = len(safejob._load_manifest())
            msg = (tr("以下 {n} 个由本程序生成的文件已超过 {d} 天，确定后会移到回收站：").format(n=len(ds), d=days) if ds else
                   tr("目前没有到期的文件。清单中共记录 {t} 个生成文件，之后只会清理其中超过 {d} 天且未被修改的项目。")
                   .format(t=total, d=days))
            if not ConfirmDialog(self, "定时删除生成文件", msg,
                                 [os.path.relpath(x, self.out_root) if x.startswith(self.out_root) else x for x in ds],
                                 note=tr("你自己放进输出目录的文件、以及生成后被修改过的文件都不会被删除。"),
                                 ok_text="确定").ask():
                return
        super().accept()

    def pick_palette(self, kind, key):
        self.pal[kind] = key
        for k, b in self.swatches[kind].items():
            b.setChecked(k == key)
        self.main.apply_palette(self.pal["bg"], self.pal["accent"])

    def done(self, r):
        if r == 0:   # 未保存：恢复原来的颜色
            cfg = self.main.cfg
            self.main.apply_palette(cfg.get("bg_preset", "default"), cfg.get("accent_preset", "blue"))
        super().done(r)

    def snapshot(self):
        return (self.pal["bg"], self.pal["accent"], self.rb_hide.isChecked(), tuple(w.isChecked() for w in self.sw.values()),
                tuple(w.value() for w in self.num.values()), self.days.currentData(),
                self.hist.currentData(), self.out_root)

    def showEvent(self, e):
        super().showEvent(e)
        if not hasattr(self, "_snap"):
            self._snap = self.snapshot()

    def reject(self):
        """有未保存的修改时，先询问是否保存。"""
        if getattr(self, "_asking", False) or not hasattr(self, "_snap") or self.snapshot() == self._snap:
            return super().reject()
        self._asking = True
        r = UnsavedDialog(self.main).exec()
        self._asking = False
        if r == 1:
            self.accept()
        elif r == 2:
            super().reject()

    def apply(self):
        cfg = self.main.cfg
        cfg["close_choice"] = "hide" if self.rb_hide.isChecked() else "quit"
        for k, sw in self.sw.items():
            cfg[k] = sw.isChecked()
        for k, sp in self.num.items():
            cfg[k] = sp.value()
        cfg["auto_delete_days"] = self.days.currentData()
        cfg["history_days"] = self.hist.currentData()
        cfg["bg_preset"], cfg["accent_preset"] = self.pal["bg"], self.pal["accent"]
        if self.out_root != self.main.out_root:
            self.main.out_root = cfg["out_root"] = self.out_root


class TimelineRail(QWidget):
    """时间线竖线 + 圆点。"""
    def __init__(self, first=False, last=False):
        super().__init__()
        self.first, self.last = first, last
        self.setFixedWidth(22)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x, y = self.width() / 2, 22
        p.setPen(QPen(QColor(C("areab")), 2))
        p.drawLine(int(x), 0 if not self.first else y, int(x), self.height() if not self.last else y)
        p.setPen(QPen(QColor(C("muted")), 1.5))
        p.setBrush(QColor(C("frame")))
        p.drawEllipse(int(x - 5), y - 5, 10, 10)


class HistoryDialog(StyledDialog):
    """历史记录：按日期分组的时间线，显示保留期内的全部转换。"""
    WEEK = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

    def __init__(self, main):
        super().__init__(main, "历史记录")
        self.main = main
        days = main.sec("history_days")
        cut = time.time() - days * 86400
        self.items = [h for h in load_history() if h.get("t", 0) >= cut][::-1]
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("最近 {d} 天的转换记录（可在「设置 → 安全」修改）").format(d=days), objectName="capHint"))
        top.addStretch()
        self.q = QLineEdit()
        self.q.setPlaceholderText(tr("搜索文件名"))
        self.q.setFixedWidth(220)
        self.q.textChanged.connect(self.fill)
        top.addWidget(self.q)
        self.content.addLayout(top)
        self.box = QVBoxLayout()
        self.box.setSpacing(0)
        self.content.addLayout(self.box)
        self.content.addStretch()
        self.fill()

    def clear_box(self):
        while self.box.count():
            it = self.box.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def fill(self, *_):
        self.clear_box()
        q = self.q.text().strip().lower()
        rows = [h for h in self.items if not q or q in os.path.basename(h["src"]).lower()
                or any(q in os.path.basename(f).lower() for f in h["files"])][:300]
        if not rows:
            self.box.addWidget(QLabel(tr("暂无转换记录"), objectName="hint"))
            return
        day = None
        for i, h in enumerate(rows):
            lt = time.localtime(h["t"])
            d = time.strftime("%Y-%m-%d", lt)
            if d != day:
                day = d
                txt = (f"{lt.tm_year}年{lt.tm_mon}月{lt.tm_mday}日{self.WEEK[lt.tm_wday]}" if LANG == "zh"
                       else time.strftime("%b %d, %Y ", lt) + tr(self.WEEK[lt.tm_wday]))
                pr = QHBoxLayout()
                pr.setContentsMargins(0, 10 if i else 0, 0, 6)
                pr.addSpacing(40)
                pr.addWidget(QLabel(txt, objectName="datePill"))
                pr.addStretch()
                w = QWidget()
                w.setLayout(pr)
                self.box.addWidget(w)
            nxt_same = i + 1 < len(rows) and time.strftime("%Y-%m-%d", time.localtime(rows[i + 1]["t"])) == d
            self.box.addWidget(self.entry(h, lt, last=not nxt_same))

    def entry(self, h, lt, last):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        tm = QLabel(time.strftime("%H:%M", lt), objectName="tlTime")
        tm.setFixedWidth(40)
        tm.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        tm.setContentsMargins(0, 14, 0, 0)
        row.addWidget(tm)
        row.addWidget(TimelineRail(last=last))
        card = QFrame(objectName="tlCard")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(14, 10, 10, 10)
        tx = QVBoxLayout()
        tx.setSpacing(3)
        title = QLabel(f"{os.path.basename(h['src'])}  →  {h['fmt']}", objectName="tlTitle")
        tx.addWidget(title)
        outs = h["files"]
        state = tr(LEVEL_TEXT.get(h["state"], h["state"]))
        sub = f"{tr(h.get('via', ''))} · {state}"
        if outs:
            names = "、".join(os.path.basename(f) for f in outs[:3]) + ("…" if len(outs) > 3 else "")
            sub += " · " + names
        elif h.get("error"):
            sub += " · " + h["error"][:80]
        sl = QLabel(sub, objectName="tlSub")
        sl.setWordWrap(True)
        tx.addWidget(sl)
        cl.addLayout(tx, 1)
        alive = [f for f in outs if os.path.exists(f)]
        if alive:
            b1 = QPushButton(tr("打开"))
            b1.clicked.connect(lambda _, f=alive[0]: os.startfile(f))
            b2 = QPushButton(tr("定位"))
            b2.clicked.connect(lambda _, f=alive[0]: subprocess.Popen(["explorer", "/select,", os.path.normpath(f)]))
            cl.addWidget(b1)
            cl.addWidget(b2)
        elif outs:
            cl.addWidget(QLabel(tr("已删除"), objectName="hint"))
        card.setToolTip("\n".join([h["src"]] + outs))
        v = QVBoxLayout()
        v.setContentsMargins(0, 4, 0, 4)
        v.addWidget(card)
        row.addLayout(v, 1)
        return w


class HelpDialog(StyledDialog):
    """帮助手册：左侧章节目录，右侧内容。"""
    def __init__(self, main):
        super().__init__(main, "帮助手册")
        h = QHBoxLayout()
        h.setSpacing(12)
        nav = QFrame(objectName="cats")
        nav.setFixedWidth(256)
        self.nl = nl = QVBoxLayout(nav)
        nl.setContentsMargins(6, 6, 6, 6)
        nl.setSpacing(4)
        self.tb = QTextBrowser()
        self.tb.setOpenExternalLinks(True)
        self.css = (f"<style>h2{{color:{C('text')};font-size:18px}} h3{{color:{C('accent')};margin-top:14px}} "
                    f"p,li{{color:{C('text')}}} li{{margin:5px 0}} code{{color:{C('warn')}}}</style>")
        self.navs = []
        nl.addStretch()
        h.addWidget(nav)
        h.addWidget(self.tb, 1)
        self.content.addLayout(h, 1)
        self.load_lang()

    def load_lang(self):
        """按当前界面语言加载章节；切换语言时重新调用。"""
        for b in self.navs:
            self.nl.removeWidget(b)
            b.deleteLater()
        self.navs = []
        chapters = HELP["en" if LANG == "en" else "zh"]
        for i, (title, html) in enumerate(chapters):
            b = QPushButton(title.replace("&", "&&"), checkable=True, autoExclusive=True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, html=html: self.tb.setHtml(self.css + html))
            self.nl.insertWidget(i, b)
            self.navs.append(b)
        self.navs[0].setChecked(True)
        self.tb.setHtml(self.css + chapters[0][1])


class Guide(StyledDialog):
    """新手引导：逐步介绍各模块，并高亮对应模块框；可切换语言，与主程序同步。"""
    def __init__(self, main):
        super().__init__(main, "使用引导", lang_btn=True, overlay=True)
        self.main = main
        self.i = 0
        self.setFixedWidth(430)
        self.titlebar.btn_lang.clicked.connect(self.switch_lang)
        v = self.content
        v.setContentsMargins(22, 8, 22, 16)
        self.head = QLabel(objectName="cardTitle")
        self.head.setStyleSheet("font-size:17px")
        self.body = QLabel(wordWrap=True)
        self.body.setStyleSheet("color:" + C("muted"))
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
        # 浮在主窗口内、被介绍的模块中央；没有对应模块时居中
        fr = self.main.frame
        target = {"in": self.main.card_in, "fmt": self.main.card_fmt, "out": self.main.card_out,
                  "side": self.main.side}.get(card)
        c = target.mapTo(fr, target.rect().center()) if target else fr.rect().center()
        x = min(max(c.x() - self.width() // 2, 12), fr.width() - self.width() - 12)
        y = min(max(c.y() - self.height() // 2, 40), fr.height() - self.height() - 12)
        self.move(x, y)


class TaskDialog(StyledDialog):
    """批量任务：查看逐文件结果、取消、只重试失败项。"""
    def __init__(self, main):
        super().__init__(main, "任务")
        self.main = main
        self.keep = True
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(720, 460)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("任务 / 文件"), tr("状态"), tr("说明")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(1, 110)
        self.tree.setColumnWidth(2, 260)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setIndentation(18)
        self.content.addWidget(self.tree, 1)
        h = QHBoxLayout()
        for text, fn, obj in (("取消任务", self.do_cancel, ""), ("重试失败项", self.do_retry, "primary"),
                              ("清除已结束", self.do_clear, "")):
            b = QPushButton(tr(text), objectName=obj)
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch()
        self.sum = QLabel(objectName="hint")
        h.addWidget(self.sum)
        self.content.addLayout(h)

    def current(self):
        it = self.tree.currentItem()
        while it and it.parent():
            it = it.parent()
        tid = it.data(0, Qt.ItemDataRole.UserRole) if it else None
        return next((t for t in self.main.tasks if t["id"] == tid), None)

    def refresh(self):
        cur = self.current()
        open_ids = {self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
                    for i in range(self.tree.topLevelItemCount()) if self.tree.topLevelItem(i).isExpanded()}
        self.tree.clear()
        for t in reversed(self.main.tasks):
            rs = t["results"]
            done = sum(1 for r in rs if r)
            bad = sum(1 for r in rs if r and r["state"] == "failed")
            state = {"running": tr("转换中"), "done": tr("已完成"), "cancelled": tr("已取消")}[t["state"]]
            top = QTreeWidgetItem([f"#{t['id']}  {t['source']} → {t['label']}   ({done}/{len(rs)})", state,
                                   (tr("失败 {n} 个").format(n=bad) if bad else "") +
                                   (("  ⚠ " + tr("资源限制未生效")) if t["limit"] else "")])
            top.setData(0, Qt.ItemDataRole.UserRole, t["id"])
            for f, r in zip(t["files"], rs):
                st = r["state"] if r else ("running" if t["state"] == "running" else "cancelled")
                note = r["error"] if r and r["error"] else "；".join(tr(n) for n in (r["notes"] if r else []))
                ch = QTreeWidgetItem([os.path.basename(f), tr(LEVEL_TEXT[st]), note])
                ch.setToolTip(0, f)
                ch.setToolTip(2, note)
                ch.setForeground(1, QBrush(QColor(LEVEL_COLOR.get(st, "#9ab"))))
                top.addChild(ch)
            self.tree.addTopLevelItem(top)
            top.setExpanded(t["id"] in open_ids or t["state"] == "running" or len(self.main.tasks) == 1)
            if cur and cur["id"] == t["id"]:
                self.tree.setCurrentItem(top)
        n = sum(1 for t in self.main.tasks if t["state"] == "running")
        self.sum.setText(tr("进行中 {n} 个").format(n=n))

    def do_cancel(self):
        t = self.current()
        if t:
            self.main.cancel_task(t)

    def do_retry(self):
        t = self.current()
        if t and t["state"] != "running":
            self.main.retry_task(t)

    def do_clear(self):
        self.main.tasks = [t for t in self.main.tasks if t["state"] == "running"]
        self.refresh()



class PresetDialog(StyledDialog):
    """转换预设：格式 + 参数（质量、最长边、页码），主窗口与悬浮球共用。"""
    CATS = (("图像", "image", converter.IMAGE_FORMATS), ("文档", "doc", converter.DOC_FORMATS),
            ("表格", "sheet", converter.SHEET_FORMATS), ("向量", "vector", converter.VECTOR_FORMATS),
            ("视频", "video", converter.VIDEO_FORMATS))

    def __init__(self, main):
        super().__init__(main, "转换预设")
        import copy
        self.items = copy.deepcopy(main.presets())
        self.resize(700, 460)
        body = QHBoxLayout()
        body.setSpacing(12)
        left = QFrame(objectName="navPanel")
        ll = QVBoxLayout(left)
        ll.setContentsMargins(6, 6, 6, 6)
        ll.setSpacing(6)
        self.lst = QListWidget(objectName="plain")
        self.lst.setStyleSheet("QListWidget{background:transparent;border:none}")
        ll.addWidget(self.lst, 1)
        lh = QHBoxLayout()
        lh.setSpacing(6)
        for text, fn, obj in (("新建", self.add, "primary"), ("删除", self.remove, "")):
            b = QPushButton(tr(text), objectName=obj)
            b.clicked.connect(fn)
            lh.addWidget(b, 1)
        ll.addLayout(lh)
        left.setFixedWidth(210)
        body.addWidget(left)
        self.name = QLineEdit()
        self.cat = QComboBox()
        for name, kind, _ in self.CATS:
            self.cat.addItem(tr(name), kind)
        self.fmt = QComboBox()
        self.quality = QSpinBox()
        self.quality.setRange(0, 100)
        self.quality.setSuffix(" %")
        self.quality.setSpecialValueText(tr("默认"))
        self.quality.setToolTip(tr("质量（JPEG/WEBP/AVIF/HEIC）"))
        self.side = QSpinBox()
        self.side.setRange(0, 20000)
        self.side.setSingleStep(100)
        self.side.setSuffix(" px")
        self.side.setSpecialValueText(tr("不缩放"))
        self.side.setToolTip(tr("最长边（像素，图像 / 视频）"))
        self.pages = QLineEdit()
        self.pages.setPlaceholderText(tr("例如 1-3,5；留空为全部"))
        self.vcodec = QComboBox()
        for key, label in videoconv.CODEC_CHOICES:
            self.vcodec.addItem(tr(label), key)
        right = QFrame(objectName="panel")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 10, 16, 14)
        rl.setSpacing(6)
        for sec, rows in (("基本", (("名称", self.name), ("类别", self.cat), ("格式", self.fmt))),
                          ("参数", (("质量", self.quality), ("最长边", self.side), ("页码 / 帧", self.pages),
                                    ("视频编码", self.vcodec)))):
            rl.addWidget(QLabel(tr(sec), objectName="section"))
            form = QGridLayout()
            form.setHorizontalSpacing(14)
            form.setVerticalSpacing(8)
            form.setColumnMinimumWidth(0, 90)
            form.setColumnStretch(1, 1)
            for i, (t, w) in enumerate(rows):
                form.addWidget(QLabel(tr(t), objectName="capHint"), i, 0)
                form.addWidget(w, i, 1)
            rl.addLayout(form)
            rl.addSpacing(4)
        self.err = QLabel(objectName="warn")
        rl.addWidget(self.err)
        rl.addStretch()
        body.addWidget(right, 1)
        self.content.addLayout(body, 1)
        h = QHBoxLayout()
        h.addStretch()
        c = QPushButton(tr("取消"))
        c.clicked.connect(self.reject)
        ok = QPushButton(tr("保存"), objectName="primary")
        ok.clicked.connect(self.accept)
        h.addWidget(c)
        h.addWidget(ok)
        self.content.addSpacing(6)
        self.content.addLayout(h)
        self.lst.currentRowChanged.connect(self.load_item)
        self.cat.currentIndexChanged.connect(self.fill_fmts)
        for w in (self.name, self.pages):
            w.textEdited.connect(self.store)
        for w in (self.quality, self.side):
            w.valueChanged.connect(self.store)
        self.fmt.currentIndexChanged.connect(self.store)
        self.vcodec.currentIndexChanged.connect(self.store)
        self.loading = False
        self.refill()
        if not self.items:
            self.add()

    def refill(self):
        row = self.lst.currentRow()
        self.lst.clear()
        for p in self.items:
            self.lst.addItem(p["name"])
        self.lst.setCurrentRow(min(max(row, 0), len(self.items) - 1))
        self.enable(bool(self.items))

    def enable(self, on):
        for w in (self.name, self.cat, self.fmt, self.quality, self.side, self.pages):
            w.setEnabled(on)
        self.vcodec.setEnabled(on and self.cat.currentData() == "video")

    def fill_fmts(self):
        kind = self.cat.currentData()
        fmts = next(f for _, k, f in self.CATS if k == kind)
        keep = self.fmt.currentText()
        self.fmt.blockSignals(True)
        self.fmt.clear()
        self.fmt.addItems(fmts)
        if keep in fmts:
            self.fmt.setCurrentText(keep)
        self.fmt.blockSignals(False)
        self.side.setEnabled(kind in ("image", "video"))
        self.vcodec.setEnabled(kind == "video")
        self.store()

    def load_item(self, row):
        if not (0 <= row < len(self.items)):
            return
        p = self.items[row]
        self.loading = True
        self.name.setText(p["name"])
        self.cat.setCurrentIndex([k for _, k, _ in self.CATS].index(p["kind"]))
        self.fill_fmts()
        self.fmt.setCurrentText(p["fmt"])
        self.quality.setValue(p.get("quality") or 0)
        self.side.setValue(p.get("max_side") or 0)
        self.pages.setText(p.get("pages") or "")
        i = self.vcodec.findData(p.get("vcodec") or "auto")
        self.vcodec.setCurrentIndex(max(i, 0))
        self.loading = False

    def store(self, *_):
        row = self.lst.currentRow()
        if self.loading or not (0 <= row < len(self.items)):
            return
        p = self.items[row]
        p.update(name=self.name.text().strip() or p["name"], kind=self.cat.currentData(), fmt=self.fmt.currentText(),
                 quality=self.quality.value(),
                 max_side=self.side.value() if self.cat.currentData() in ("image", "video") else 0,
                 pages=self.pages.text().strip(),
                 vcodec=self.vcodec.currentData() if self.cat.currentData() == "video" else "")
        self.lst.item(row).setText(p["name"])

    def add(self):
        self.items.append({"id": str(int(time.time() * 1000)), "name": tr("新预设") + f" {len(self.items) + 1}",
                           "kind": "image", "fmt": "JPEG", "quality": 85, "max_side": 1600, "pages": ""})
        self.refill()
        self.lst.setCurrentRow(len(self.items) - 1)

    def remove(self):
        row = self.lst.currentRow()
        if 0 <= row < len(self.items):
            self.items.pop(row)
            self.refill()

    def accept(self):
        for p in self.items:
            try:
                if p.get("pages") and not converter.parse_pages(p["pages"], 100000):
                    raise ValueError
            except ValueError:
                self.err.setText(tr("「{n}」的页码格式不正确，例如 1-3,5").format(n=p["name"]))
                return
        super().accept()


class BallSettings(StyledDialog):
    """常用格式设置：最多 6 种。"""
    MAX = 6

    def __init__(self, main):
        super().__init__(main, "悬浮球 · 常用格式")
        self.selected = list(main.cfg.get("ball_formats", []))[:self.MAX]
        self.setMinimumWidth(640)
        lay = self.content
        lay.setSpacing(8)
        lay.setContentsMargins(lay.contentsMargins().left(), 4, lay.contentsMargins().right(),
                               lay.contentsMargins().bottom())
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(QLabel(tr("悬浮球上显示的格式（最多 6 种）"),
                              objectName="cardTitle"))
        self.chosen = QLabel(objectName="hint")
        head.addWidget(self.chosen, 1)
        self.count = QLabel(objectName="pill")
        self.count.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        head.addWidget(self.count, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(head, 0)
        self.btns = []
        groups = [("图像", "image", [(f, f) for f in converter.IMAGE_FORMATS]),
                  ("文档", "doc", [(f, f) for f in converter.DOC_FORMATS]),
                  ("表格", "sheet", [(f, f) for f in converter.SHEET_FORMATS]),
                  ("向量", "vector", [(f, f) for f in converter.VECTOR_FORMATS]),
                  ("视频", "video", [(f, f) for f in converter.VIDEO_FORMATS])]
        if main.presets():
            groups.append(("预设", "preset", [(p["id"], p["name"]) for p in main.presets()]))
        panel = QFrame(objectName="panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 6, 12, 12)
        pl.setSpacing(4)
        for name, kind, fmts in groups:
            pl.addWidget(QLabel(tr(name), objectName="section"))
            g = QGridLayout()
            g.setSpacing(6)
            for k, (f, label) in enumerate(fmts):
                b = QPushButton(label, objectName="fmt", checkable=True)
                b.setFixedSize(66 if kind != "preset" else 138, 30)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                key = f"{kind}:{f}"
                b.setChecked(key in self.selected)
                b.toggled.connect(lambda on, key=key, b=b: self.toggle(key, on, b))
                g.addWidget(b, k // 9, k % 9, Qt.AlignmentFlag.AlignLeft)
                self.btns.append(b)
            g.setColumnStretch(9, 1)
            pl.addLayout(g)
        lay.addWidget(panel)
        lay.addStretch(1)   # 多余高度放到底部，标题行紧贴顶部
        foot = QHBoxLayout()
        self.auto_open = QCheckBox(tr("完成后自动打开输出文件夹"))
        self.auto_open.setChecked(bool(main.cfg.get("ball_auto_open", False)))
        foot.addWidget(self.auto_open)
        foot.addStretch()
        c = QPushButton(tr("取消"))
        c.clicked.connect(self.reject)
        ok = QPushButton(tr("确定"), objectName="primary")
        ok.clicked.connect(self.accept)
        foot.addWidget(c)
        foot.addWidget(ok)
        lay.addLayout(foot)
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
        names = []
        for k in self.selected:
            kind, f = k.split(":", 1)
            p = self.parent().preset_by_id(f) if kind == "preset" else None
            names.append(p["name"] if p else f)
        self.count.setText(tr("已选 {n}/{m}").format(n=len(self.selected), m=self.MAX))
        self.chosen.setText("  ·  ".join(names) if names else tr("点击下方格式加入悬浮球"))


if __name__ == "__main__":
    try:  # 让任务栏使用本程序自己的图标，而不是 Python 的
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GeShiZhuanHuanQi.App")
    except Exception:
        pass
    import multiprocessing
    multiprocessing.freeze_support()   # 打包后子进程（隔离处理）需要
    import tempfile
    tempfile.tempdir = safejob.tmp_root()  # 本程序的临时文件统一放在这里，便于清理
    if len(sys.argv) == 4 and sys.argv[1] == "--selftest":  # 自检：隔离进程转换 src → out_dir 为 PDF
        with open(os.path.join(sys.argv[3], "selftest.txt"), "w", encoding="utf-8") as f:
            try:
                f.write(repr(safejob.convert_one(sys.argv[2], sys.argv[3], "PDF", "doc", dict(SEC_DEFAULTS))))
            except Exception as e:
                f.write("ERR " + repr(e))
        os._exit(0)
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(os.path.join(ASSETS, "icon.ico")))
    try:
        with open(CONFIG, encoding="utf-8") as f:
            _c = json.load(f)
        THEME = _c.get("theme", "dark")
        compose_palette(_c.get("bg_preset"), _c.get("accent_preset"))
    except Exception:
        THEME = "dark"
    THEME = THEME if THEME in THEMES else "dark"
    app.setStyleSheet(build_qss(THEME))
    w = Main()
    w.add_paths(sys.argv[1:])
    app.setQuitOnLastWindowClosed(False)
    w.show()
    w.apply_ball()
    QTimer.singleShot(3000, w.run_auto_delete)
    w.auto_timer = QTimer(w, interval=3600 * 1000, timeout=w.run_auto_delete)
    w.auto_timer.start()
    if not w.cfg.get("guided"):
        QTimer.singleShot(400, w.open_guide)
    code = app.exec()
    os._exit(code)  # 直接结束进程，避免后台库线程拖住退出
