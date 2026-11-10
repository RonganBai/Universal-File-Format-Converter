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

from PyQt6.QtCore import QEasingCurve, QByteArray, Qt, QThread, pyqtSignal, pyqtProperty, QPropertyAnimation, QUrl, QPoint, QTimer, QMimeData, QFileInfo, QSize
from PyQt6.QtGui import QCursor, QImageReader, QBrush, QPainter, QColor, QDesktopServices, QIcon, QPixmap, QKeySequence, QShortcut, QAction
from PyQt6.QtWidgets import (QApplication, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QStackedWidget, QVBoxLayout, QWidget, QProgressBar, QFrame,
                             QDialog, QCheckBox, QDialogButtonBox, QRadioButton, QSystemTrayIcon, QMenu,
                             QFileIconProvider, QAbstractItemView, QTextBrowser,
                             QScrollArea, QSpinBox, QComboBox, QTreeWidget, QTreeWidgetItem, QLineEdit,
                             QHeaderView)

import converter
import safejob

SEC_DEFAULTS = {"ask_on_fail": True, "share_confirm": True, "strip_meta": True, "clean_temp": True, "isolate": True,
                "timeout_s": 300, "mem_mb": 4096, "max_mb": 500, "max_mpix": 200, "max_unzip_mb": 2048,
                "auto_delete_days": 0}
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
    "preset": "使用保存的格式与参数（质量、最长边、页码）转换，主窗口与悬浮球共用。",
}
CAPS_COMMON = "无法识别的文件只生成信息预览；视频转 GIF / WEBP 为动图，转其他格式只取一帧，音频只生成文件信息；结果会标注「完整转换」「部分输出」「仅生成预览」或「失败」。"
SYNC_ENV = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")

VERSION = "1.8.1"
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
QPushButton#tool { background:transparent; border:1px solid #3a3a3a; padding:4px 12px; border-radius:14px; }
QPushButton#tool:hover { background:#2f2f2f; border-color:#0a84ff; }
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
QPushButton#fmt:checked { background:#0a64c8; border-color:#4ea1ff; color:white; }
QPushButton#go { background:#0a64c8; border:1px solid #0a64c8; color:white; font-weight:bold; min-height:34px;
                 min-width:150px; border-radius:6px; padding:4px 16px; }
QPushButton#go:hover { background:#0a84ff; } QPushButton#go:disabled { background:#2f2f2f; color:#777; border-color:#3c3c3c; }
QProgressBar#mini { border:none; background:#333; max-height:6px; min-height:6px; border-radius:3px; }
QProgressBar#mini::chunk { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0a64c8,stop:1 #4ea1ff); border-radius:3px; }
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
QSpinBox, QComboBox { background:#2b2b2b; border:1px solid #444; border-radius:5px; padding:3px 6px; min-width:90px; }
QComboBox QAbstractItemView { background:#2b2b2b; selection-background-color:#0a84ff; }
QScrollArea { background:transparent; border:none; }
#warn { color:#e3b341; font-size:12px; }
QTextBrowser { background:#1c1c1c; border:1px solid #333; border-radius:6px; }
"""


LANG = "zh"
EN = {
    "格式转换器": "Format Converter",
    "添加文件": "Add files", "添加文件夹": "Add folder", "清空": "Clear", "移除所选": "Remove",
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
    "转换预设…": "Presets…",
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
    "名称": "Name", "类别": "Category", "格式": "Format", "质量（JPEG/WEBP/AVIF/HEIC）": "Quality (JPEG/WEBP/AVIF/HEIC)",
    "最长边（像素，仅图像）": "Longest side (px, images only)", "页码 / 帧": "Pages / frames",
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
    "悬浮球": "Floating ball", "常用格式…": "Quick formats…", "常用格式设置": "Quick format settings", "设置": "Settings",
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
        ("① 输入文件", "把文件或文件夹拖到窗口任意位置，或点「添加文件」。支持多选，选中后按 Delete 或「移除所选」可删掉。", "in"),
        ("② 目标格式", "在左侧选分类，在右侧选格式或预设，再点「开始转换」，即可处理列表里的全部文件。", "fmt"),
        ("③ 转换结果", "转换好的文件显示在这里：双击直接打开，多选后可批量打开、定位到文件夹或分享。", "out"),
        ("悬浮球与托盘", "用主页左上角的「悬浮球」开关开启屏幕边缘悬浮球，把文件拖到气泡上就能快速转换。"
                         "关闭窗口时程序可隐藏到右下角托盘，右键托盘图标即可打开各项功能。标题栏的「?」随时查看帮助。", None),
    ],
    "en": [
        ("Welcome to Format Converter", "Add files, choose a target format and click Start, then open or share the results. "
                                        "Here is a quick look at each panel.", None),
        ("① Input files", "Drop files or folders anywhere in the window, or click “Add files”. Select several and press "
                          "Delete or “Remove” to take them out.", "in"),
        ("② Target format", "Pick a category on the left and a format or preset on the right. Click Start to convert all files in the list.", "fmt"),
        ("③ Results", "Converted files appear here. Double-click to open; multi-select to open, locate or share.", "out"),
        ("Floating ball & tray", "Turn on the screen-edge floating ball with the “Floating ball” switch on the main page and drop files on it for quick "
                                 "conversions. When the window is closed the app can hide in the system tray — right-click "
                                 "its icon for quick actions. Click “?” in the title bar for help at any time.", None),
    ],
}

HELP_ZH = """
<h2>格式转换器 帮助手册</h2>
<h3>1. 基本流程</h3>
<ol><li><b>添加文件</b>：拖到窗口任意位置，或点「添加文件」「添加文件夹」。文件夹会递归加入其中所有文件。</li>
<li><b>选择格式</b>：在「② 目标格式」选中格式或预设，再点击「开始转换」，处理列表中的<b>全部</b>文件。</li>
<li><b>查看结果</b>：结果出现在「③ 转换结果」，同时保存在输出文件夹。</li></ol>
<h3>2. 输入文件</h3>
<ul><li>任意类型都可以拖入：图片、PDF、Word/ODT、Excel/CSV、文本、音视频等；无法识别内容的文件会生成文件信息预览。</li>
<li>按住 Ctrl / Shift 多选，按 <b>Delete</b> 或「移除所选」删除；「清空」移除全部。</li></ul>
<h3>3. 目标格式</h3>
<ul><li><b>图像</b>：PNG、JPG、WEBP、TIFF、ICO、HEIC 等 30 种。多页文档会按页输出多张图片。</li>
<li><b>文档</b>：PDF、DOCX、DOC、RTF、ODT、XPS 等。PDF 中的表格会尽量保留为表格。</li>
<li><b>表格</b>：XLSX、XLSM、CSV。PDF / Word 中识别出的表格各放一张工作表，合并单元格会保留。</li>
<li><b>向量</b>：SVG、AI、EPS、PS、EMF、WMF 等 11 种；PDF→SVG/AI 为真矢量，其他来源会嵌入图像。</li>
<li>DJVU 需要安装 DjVuLibre，JBG 需要 JBIG-KIT 的 pbmtojbg。</li></ul>
<h3>4. 转换结果</h3>
<ul><li><b>双击</b>文件直接用默认程序打开。</li>
<li>多选后可批量 <b>打开</b>、<b>定位</b>（在资源管理器中选中）或 <b>分享</b>。</li>
<li>分享方式：Windows 共享面板；复制文件后在微信 / QQ / 邮件中直接粘贴；复制路径；打包为 ZIP。多个文件使用 Windows 共享时会先打包成一个 ZIP。</li>
<li>「清空记录」只清除列表，不会删除文件。</li></ul>
<h3>5. 输出位置</h3>
<ul><li>默认输出到 <code>用户目录\\格式转换输出\\日期</code>，可在主页「设置」中修改根目录，每天自动建新的日期文件夹。「定位」在未选中结果时直接打开输出文件夹。</li>
<li>同名文件不会被覆盖，会自动加序号。</li>
<li>如果输出目录无法写入（例如被 Windows「受控文件夹访问」拦截），默认会暂停并让你选择其他目录、存到「下载」或取消。</li></ul>
<h3>安全</h3>
<ul><li>「设置 → 安全」可开关：输出失败时询问、分享前确认、移除敏感元数据、自动清理临时文件、隔离进程处理，并设置超时、内存、文件大小、像素和解压体积上限。</li>
<li>定时删除生成文件：只清理本程序生成并记录在清单中、超过指定天数且未被修改的文件，移到回收站；首次启用会先预览清单。</li>
<li>每个结果会标注「完整转换」「部分输出」「仅生成预览」或「失败」，以及元数据是否已清理；分享前会标出需要人工检查的文件。</li>
<li>隔离处理时会校验内存与优先级限制是否成功应用，未生效会提示。</li></ul>
<h3>任务与预设</h3>
<ul><li>工具栏「任务」查看主窗口与悬浮球的全部批量任务：逐文件状态与错误、取消（已完成的结果会保留）、只重试失败项。</li>
<li>「转换预设…」保存格式与参数（JPEG 质量、最长边、页码），在「② 目标格式 → 预设」或悬浮球常用格式中直接使用。</li>
<li>始终开启：原文件只读；结果写完再发布、不覆盖已有文件；表格防公式注入。</li></ul>
<h3>6. 悬浮球</h3>
<ul><li>用主页工具栏的「悬浮球」滑块开关开启或关闭，「常用格式…」选择最多 6 种格式；悬浮球可吸附在屏幕左、右、顶部边缘，拖动即可换位置。</li>
<li>点击气泡可展开。拖入文件后可展开完整列表或逐个移除文件，点击常用格式或预设即可转换。</li>
<li>拖动气泡时会变为圆球，保留转换进度或结果提示。松手后会吸附回屏幕边缘。</li>
<li>转换中再次拖入的文件会进入下一批。当前任务可取消，完成后可打开输出、查看失败或重试失败项。自动打开输出文件夹可在「常用格式…」中开启。</li>
<li>右键菜单可打开主窗口、查看任务、编辑常用格式、打开输出文件夹、锁定或重置位置，以及退出。</li></ul>
<h3>7. 系统托盘</h3>
<ul><li>程序运行时右下角托盘会显示图标，单击 / 双击打开主窗口，右键可快速添加文件、打开输出文件夹、开关悬浮球、查看引导与帮助、退出。</li>
<li>第一次点 ✕ 时会询问「完全退出」还是「隐藏到系统托盘」，之后按你的选择执行，可在主页「设置」中修改。</li></ul>
<h3>8. 其他</h3>
<ul><li>标题栏「EN / 中文」切换语言；主页工具栏的「使用引导」「帮助手册」「设置」随时可用（F1 也可打开本手册）。</li>
<li>设置保存在 <code>%APPDATA%\\格式转换器\\config.json</code>。</li></ul>
"""

HELP_EN = """
<h2>Format Converter — Help</h2>
<h3>1. Basics</h3>
<ol><li><b>Add files</b>: drop them anywhere in the window, or use “Add files” / “Add folder” (folders are added recursively).</li>
<li><b>Pick a format</b>: select a format or preset in “② Target format”, then click Start to convert <b>all</b> listed files.</li>
<li><b>See results</b>: they appear in “③ Results” and are saved in the output folder.</li></ol>
<h3>2. Input files</h3>
<ul><li>Any type can be dropped: images, PDF, Word/ODT, Excel/CSV, text, audio/video… Unknown files produce an info preview.</li>
<li>Use Ctrl / Shift to multi-select, then <b>Delete</b> or “Remove”; “Clear” removes everything.</li></ul>
<h3>3. Target formats</h3>
<ul><li><b>Image</b>: 30 formats incl. PNG, JPG, WEBP, TIFF, ICO, HEIC. Multi-page documents give one image per page.</li>
<li><b>Document</b>: PDF, DOCX, DOC, RTF, ODT, XPS… Tables in PDFs are kept as tables where possible.</li>
<li><b>Spreadsheet</b>: XLSX, XLSM, CSV. Each table found in a PDF / Word file becomes a sheet; merged cells are kept.</li>
<li><b>Vector</b>: 11 formats incl. SVG, AI, EPS, PS, EMF, WMF. PDF→SVG/AI is true vector; other sources embed an image.</li>
<li>DJVU needs DjVuLibre; JBG needs pbmtojbg from JBIG-KIT.</li></ul>
<h3>4. Results</h3>
<ul><li><b>Double-click</b> a file to open it.</li>
<li>Multi-select to <b>Open</b>, <b>Locate</b> or <b>Share</b> in bulk.</li>
<li>Sharing: Windows Share panel; copy files and paste them into chat or email; copy paths; pack into a ZIP. Several files are packed into one ZIP for Windows Share.</li>
<li>“Clear list” only clears the list — files are not deleted.</li></ul>
<h3>5. Output location</h3>
<ul><li>Default: <code>%USERPROFILE%\\格式转换输出\\date</code>. Change the root in “Settings”; a dated folder is created each day. “Locate” with nothing selected opens the output folder.</li>
<li>Existing files are never overwritten — a number is appended.</li>
<li>If the folder is not writable (e.g. blocked by Controlled Folder Access), the job pauses and lets you pick another folder, Downloads, or cancel.</li></ul>
<h3>Security</h3>
<ul><li>“Settings → Security” toggles: ask when output fails, confirm before sharing, remove metadata, auto-clean temp files, isolated processing; plus limits for time, memory, file size, pixels and unpacked size.</li>
<li>Auto-delete outputs: only files this app generated and recorded, older than N days and unmodified, go to the Recycle Bin; the list is previewed when you first enable it.</li>
<li>Every result is labelled Complete / Partial output / Preview only / Failed with its metadata status; sharing flags files that need a manual check.</li>
<li>Isolated processing verifies that memory and priority limits were applied and warns if not.</li></ul>
<h3>Tasks & presets</h3>
<ul><li>“Tasks” in the toolbar lists all batch jobs from the main window and the floating ball: per-file status and errors, cancel (finished results are kept), retry failed items only.</li>
<li>“Presets…” saves a format with parameters (JPEG quality, longest side, pages); use them under “② Target format → Presets” or as floating-ball quick formats.</li>
<li>Always on: sources are read-only; results are published only when complete and never overwrite; spreadsheet formula-injection protection.</li></ul>
<h3>6. Floating ball</h3>
<ul><li>Turn it on or off with the “Floating ball” switch in the toolbar and pick up to 6 formats in “Quick formats…”. It docks to the left, right or top edge — drag it to move.</li>
<li>Click the bubble to expand it. After dropping files, you can expand the list or remove files individually. Click a quick format or preset to convert.</li>
<li>While you drag the bubble, it becomes a round ball and keeps showing progress or the result. Release it to dock at a screen edge.</li>
<li>Files dropped during conversion go into the next batch. You can cancel the current job, then open the output, view failures or retry failed items when a job ends. To open the output folder automatically, enable the option in “Quick formats…”.</li>
<li>Right-click the ball to open the main window, view tasks, edit quick formats, open the output folder, lock or reset the position, or quit.</li></ul>
<h3>7. System tray</h3>
<ul><li>A tray icon appears while the app runs. Click it to open the window; right-click to add files, open the output folder, toggle the ball, see the tour / help, or quit.</li>
<li>The first time you click ✕ you are asked whether to quit or hide to the tray; the choice is remembered and can be changed in “Settings”.</li></ul>
<h3>8. Misc</h3>
<ul><li>“EN / 中文” switches the language; “Quick tour”, “Help manual” and “Settings” are in the main toolbar (F1 opens this manual).</li>
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
        body = QWidget()
        fl.addWidget(body, 1)
        root = QVBoxLayout(body)
        root.setContentsMargins(12, 4, 12, 12)
        root.setSpacing(10)

        tb = QHBoxLayout()
        tb.setSpacing(8)
        self.ball_switch = Switch()
        self.ball_switch.setChecked(bool(self.cfg.get("ball_on")))
        self.ball_switch.toggled.connect(self.set_ball)
        tb.addWidget(self.ball_switch)
        lb = self.L(QLabel(), "悬浮球")
        lb.mousePressEvent = lambda e: self.ball_switch.toggle()
        tb.addWidget(lb)
        b = self.L(QPushButton(objectName="tool"), "常用格式…")
        b.clicked.connect(self.open_ball_settings)
        tb.addWidget(b)
        b = self.L(QPushButton(objectName="tool"), "转换预设…")
        b.clicked.connect(self.open_presets)
        tb.addWidget(b)
        tb.addStretch()
        self.btn_tasks = QPushButton(objectName="tool")
        self.btn_tasks.clicked.connect(self.open_tasks)
        tb.addWidget(self.btn_tasks)
        for text, fn in (("使用引导", self.open_guide), ("帮助手册", self.open_help), ("设置", self.open_settings)):
            b = self.L(QPushButton(objectName="tool"), text)
            b.clicked.connect(fn)
            tb.addWidget(b)
        root.addLayout(tb)

        top = QHBoxLayout()
        top.setSpacing(10)
        root.addLayout(top, 6)

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
        self.results.itemDoubleClicked.connect(
            lambda it: os.startfile(it.data(Qt.ItemDataRole.UserRole)) if it.data(Qt.ItemDataRole.UserRole) else None)
        self.results.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results.customContextMenuRequested.connect(self.results_menu)
        self.results.model().rowsInserted.connect(self.update_counts)
        self.results.model().rowsRemoved.connect(self.update_counts)
        self.results.setMinimumHeight(180)
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
        rrow.addStretch()
        self.out_count = QLabel(objectName="hint")
        rrow.addWidget(self.out_count)
        v.addLayout(rrow)
        self.status = self.L(QLabel(), "就绪")
        self.status.setWordWrap(True)
        self.status.setOpenExternalLinks(True)
        v.addWidget(self.status)
        top.addWidget(self.card_out, 1)

        # ---- ② 目标格式
        self.card_fmt, v = self.card("② 目标格式", "先选择目标格式，再点「开始转换」，避免点错格式直接生成")
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
        self.cat_kinds = [g[1] for g in groups] + ["preset"]
        self.cat_btns = []
        for idx, (name, kind, fmts) in enumerate(groups):
            cb = self.L(QPushButton(checkable=True, autoExclusive=True), name, f"  ({len(fmts)})")
            cb.clicked.connect(lambda _, i=idx: self.show_cat(i))
            cb.setChecked(idx == 0)
            cl.addWidget(cb)
            self.cat_btns.append(cb)
            page = QWidget()
            g = QGridLayout(page)
            g.setContentsMargins(6, 0, 0, 0)
            g.setSpacing(7)
            for k, f in enumerate(fmts):
                b = QPushButton(f, objectName="fmt", checkable=True)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(lambda _, b=b, f=f, kind=kind: self.select(b, f, kind))
                b.kind = kind
                g.addWidget(b, k // 8, k % 8)
                self.fmt_buttons.append(b)
            g.setRowStretch(g.rowCount(), 1)
            self.stack.addWidget(page)
        self.cat_preset = self.L(QPushButton(checkable=True, autoExclusive=True), "预设")
        self.cat_preset.clicked.connect(lambda: self.show_cat(4))
        cl.addWidget(self.cat_preset)
        self.preset_page = QWidget()
        self.preset_grid = QGridLayout(self.preset_page)
        self.preset_grid.setContentsMargins(6, 0, 0, 0)
        self.preset_grid.setSpacing(7)
        self.stack.addWidget(self.preset_page)
        cl.addStretch()
        sel.addWidget(cats)
        line = QFrame()
        line.setFixedWidth(1)
        line.setStyleSheet("background:#383838")
        sel.addWidget(line)
        sel.addWidget(self.stack, 1)
        v.addLayout(sel, 1)
        self.cap_hint = QLabel(objectName="hint")
        self.cap_hint.setWordWrap(True)
        self.cap_hint.setStyleSheet("color:#9ab;font-size:12px")
        gr = QHBoxLayout()
        gr.addWidget(self.cap_hint, 1)
        self.btn_go = QPushButton(objectName="go")
        self.btn_go.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_go.clicked.connect(self.start_selected)
        gr.addWidget(self.btn_go, 0, Qt.AlignmentFlag.AlignBottom)
        v.addLayout(gr)
        self.sel = None
        root.addWidget(self.card_fmt, 4)
        self.tasks, self.task_seq, self.task_dlg = [], 0, None
        self.result_info = {}
        self.rebuild_presets()

        self.L(self.title.text, "格式转换器")
        QShortcut(QKeySequence("F1"), self, self.open_help)
        self.make_tray()
        self.retranslate()

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
        if hasattr(self, "cap_hint"):
            self.show_cat(self.stack.currentIndex())
            self.update_go()
            self.update_task_btn()
            self.rebuild_presets()

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
        for x in self.fmt_buttons:
            if x is not b:
                x.setChecked(False)
        b.setChecked(True)
        self.sel = (b, fmt, kind, params, label)
        self.update_go()

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
        self.cap_hint.setText("ⓘ " + tr(CAPS[kind]) + " " + tr(CAPS_COMMON))
        for b in self.fmt_buttons:
            b.setToolTip(tr(CAPS.get(getattr(b, "kind", "preset"), "")))

    # ---- 预设
    def presets(self):
        return self.cfg.get("presets", [])

    def preset_by_id(self, pid):
        return next((p for p in self.presets() if p["id"] == pid), None)

    @staticmethod
    def preset_params(p):
        return {k: p.get(k) for k in ("quality", "max_side", "pages") if p.get(k)}

    @staticmethod
    def preset_desc(p):
        bits = [p["fmt"]]
        if p.get("quality"):
            bits.append(tr("质量 {q}%").format(q=p["quality"]))
        if p.get("max_side"):
            bits.append(tr("最长边 {n}px").format(n=p["max_side"]))
        if p.get("pages"):
            bits.append(tr("第 {p} 页").format(p=p["pages"]))
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
            self.add_results([r for r in task["results"] if r])
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
        self.btn_tasks.setText(tr("任务") + (f" ({n})" if n else ""))

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

    def selected_results(self, need=True):
        ps = [it.data(Qt.ItemDataRole.UserRole) for it in self.results.selectedItems()]
        ps = [p for p in ps if p and os.path.exists(p)]
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


class Switch(QCheckBox):
    """滑块开关。"""
    def __init__(self):
        super().__init__()
        self.setFixedSize(40, 22)
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
        off, on = QColor("#4a4a4a"), QColor("#0a84ff")
        t = self._x
        p.setBrush(QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                          int(off.blue() + (on.blue() - off.blue()) * t)))
        p.drawRoundedRect(self.rect(), 11, 11)
        p.setBrush(QColor("white"))
        p.drawEllipse(int(3 + t * (self.width() - 22)), 3, 16, 16)


class CloseAsk(StyledDialog):
    """第一次点 ✕ 时询问关闭方式。"""
    def __init__(self, main):
        super().__init__(main, "关闭格式转换器")
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
        self.setMinimumWidth(440)
        v = self.content
        v.setContentsMargins(22, 10, 22, 16)
        lb = QLabel(msg)
        lb.setWordWrap(True)
        v.addWidget(lb)
        if items:
            shown = list(items[:10]) + ([tr("…等 {n} 个").format(n=len(items))] if len(items) > 10 else [])
            box = QLabel("\n".join("• " + x for x in shown))
            box.setStyleSheet("background:#262626;border:1px solid #353535;border-radius:6px;padding:8px;color:#ddd")
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
        self.setStyleSheet("QRadioButton{color:#e6e6e6}")
        self.resize(620, 720)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        inner = QWidget()
        sa.setWidget(inner)
        v = QVBoxLayout(inner)
        v.setContentsMargins(4, 4, 10, 4)
        v.setSpacing(10)
        self.content.addWidget(sa, 1)

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
        v.addStretch()

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
        f = QFrame(objectName="card")
        cv = QVBoxLayout(f)
        cv.setContentsMargins(14, 12, 14, 12)
        cv.setSpacing(8)
        cv.addWidget(QLabel(tr(title), objectName="cardTitle"))
        v.addWidget(f)
        return f, cv

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

    def apply(self):
        cfg = self.main.cfg
        cfg["close_choice"] = "hide" if self.rb_hide.isChecked() else "quit"
        for k, sw in self.sw.items():
            cfg[k] = sw.isChecked()
        for k, sp in self.num.items():
            cfg[k] = sp.value()
        cfg["auto_delete_days"] = self.days.currentData()
        if self.out_root != self.main.out_root:
            self.main.out_root = cfg["out_root"] = self.out_root


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


class TaskDialog(StyledDialog):
    """批量任务：查看逐文件结果、取消、只重试失败项。"""
    def __init__(self, main):
        super().__init__(main, "任务")
        self.main = main
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(720, 460)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("任务 / 文件"), tr("状态"), tr("说明")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setColumnWidth(1, 110)
        self.tree.setColumnWidth(2, 260)
        self.tree.setStyleSheet("QTreeWidget{background:#1c1c1c;border:1px solid #333;border-radius:6px}"
                                "QHeaderView::section{background:#262626;color:#aaa;border:none;padding:4px}")
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

    def reject(self):
        self.hide()


class PresetDialog(StyledDialog):
    """转换预设：格式 + 参数（质量、最长边、页码），主窗口与悬浮球共用。"""
    CATS = (("图像", "image", converter.IMAGE_FORMATS), ("文档", "doc", converter.DOC_FORMATS),
            ("表格", "sheet", converter.SHEET_FORMATS), ("向量", "vector", converter.VECTOR_FORMATS))

    def __init__(self, main):
        super().__init__(main, "转换预设")
        import copy
        self.items = copy.deepcopy(main.presets())
        self.resize(640, 420)
        body = QHBoxLayout()
        self.lst = QListWidget()
        self.lst.setFixedWidth(200)
        body.addWidget(self.lst)
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        self.name = QLineEdit()
        self.cat = QComboBox()
        for name, kind, _ in self.CATS:
            self.cat.addItem(tr(name), kind)
        self.fmt = QComboBox()
        self.quality = QSpinBox()
        self.quality.setRange(0, 100)
        self.quality.setSpecialValueText(tr("默认"))
        self.side = QSpinBox()
        self.side.setRange(0, 20000)
        self.side.setSingleStep(100)
        self.side.setSpecialValueText(tr("不缩放"))
        self.pages = QLineEdit()
        self.pages.setPlaceholderText(tr("例如 1-3,5；留空为全部"))
        rows = (("名称", self.name), ("类别", self.cat), ("格式", self.fmt), ("质量（JPEG/WEBP/AVIF/HEIC）", self.quality),
                ("最长边（像素，仅图像）", self.side), ("页码 / 帧", self.pages))
        for i, (t, w) in enumerate(rows):
            form.addWidget(QLabel(tr(t)), i, 0)
            form.addWidget(w, i, 1)
        self.err = QLabel(objectName="warn")
        form.addWidget(self.err, len(rows), 0, 1, 2)
        form.setRowStretch(len(rows) + 1, 1)
        right = QWidget()
        right.setLayout(form)
        body.addWidget(right, 1)
        self.content.addLayout(body, 1)
        h = QHBoxLayout()
        for text, fn in (("新建", self.add), ("删除", self.remove)):
            b = QPushButton(tr(text))
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch()
        c = QPushButton(tr("取消"))
        c.clicked.connect(self.reject)
        ok = QPushButton(tr("保存"), objectName="primary")
        ok.clicked.connect(self.accept)
        h.addWidget(c)
        h.addWidget(ok)
        self.content.addLayout(h)
        self.lst.currentRowChanged.connect(self.load_item)
        self.cat.currentIndexChanged.connect(self.fill_fmts)
        for w in (self.name, self.pages):
            w.textEdited.connect(self.store)
        for w in (self.quality, self.side):
            w.valueChanged.connect(self.store)
        self.fmt.currentIndexChanged.connect(self.store)
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
        self.side.setEnabled(kind == "image")
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
        self.loading = False

    def store(self, *_):
        row = self.lst.currentRow()
        if self.loading or not (0 <= row < len(self.items)):
            return
        p = self.items[row]
        p.update(name=self.name.text().strip() or p["name"], kind=self.cat.currentData(), fmt=self.fmt.currentText(),
                 quality=self.quality.value(), max_side=self.side.value() if self.cat.currentData() == "image" else 0,
                 pages=self.pages.text().strip())
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
        super().__init__(main, "常用格式设置")
        self.setStyleSheet("QCheckBox, QRadioButton{color:#e6e6e6}"
                           "QPushButton#fmt:checked{background:#0a84ff;border-color:#0a84ff;color:white}")
        self.selected = list(main.cfg.get("ball_formats", []))[:self.MAX]
        lay = self.content
        self.auto_open = QCheckBox(tr("悬浮球转换完成后自动打开输出文件夹"))
        self.auto_open.setChecked(bool(main.cfg.get("ball_auto_open", False)))
        lay.addWidget(self.auto_open)
        self.count = QLabel()
        self.count.setStyleSheet("color:#999")
        lay.addWidget(self.count)
        self.btns = []
        groups = [("图像", "image", [(f, f) for f in converter.IMAGE_FORMATS]),
                  ("文档", "doc", [(f, f) for f in converter.DOC_FORMATS]),
                  ("表格", "sheet", [(f, f) for f in converter.SHEET_FORMATS]),
                  ("向量", "vector", [(f, f) for f in converter.VECTOR_FORMATS])]
        if main.presets():
            groups.append(("预设", "preset", [(p["id"], p["name"]) for p in main.presets()]))
        for name, kind, fmts in groups:
            lay.addWidget(QLabel(tr(name)))
            g = QGridLayout()
            g.setSpacing(6)
            for k, (f, label) in enumerate(fmts):
                b = QPushButton(label, objectName="fmt", checkable=True)
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
        names = []
        for k in self.selected:
            kind, f = k.split(":", 1)
            p = self.parent().preset_by_id(f) if kind == "preset" else None
            names.append(p["name"] if p else f)
        self.count.setText(tr("选择常用格式（最多 6 种）：已选 {n}/6").format(n=len(self.selected))
                           + ("　" + "  ".join(names) if names else ""))


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
    app.setStyleSheet(QSS)
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
