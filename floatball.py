"""屏幕边缘悬浮窗。

阶段：
  bubble  收起：贴边的小气泡，显示「文件转换」或当前状态（转换中 3/8、完成 8、失败 2），点击展开
  drop    展开：等待拖入文件；拖着文件靠近时高亮投放区
  panel   面板：已拖入的文件 / 选择格式 / 当前任务进度 / 完成结果与操作
转换中再次拖入的文件排到「下一批」，当前任务完成后再选格式。
"""
import os

from PyQt6.QtCore import (Qt, QTimer, QPropertyAnimation, QParallelAnimationGroup, QRect, QRectF, QEasingCurve, QSize,
                          QThread, pyqtSignal, pyqtProperty, QPoint)
from PyQt6.QtGui import QPainter, QColor, QPixmap, QGuiApplication, QCursor, QFont, QFontMetrics, QPen
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel, QMenu,
                             QGraphicsOpacityEffect, QScrollArea, QProgressBar)

BUBBLE_T = 22      # 气泡厚度（贴边方向的尺寸）
ORB = 46           # 拖动时的球状悬浮球直径
PANEL_BG = QColor(31, 31, 31, 240)
DROP_SIZE = QSize(150, 128)
CHOOSE_W = 220
ROW_H = 20
FONT = "Microsoft YaHei UI"
BLUE, GREEN, AMBER = QColor(10, 110, 230, 191), QColor(30, 150, 90, 210), QColor(205, 130, 20, 215)

QSS = f"""
QWidget {{ background:transparent; color:#e8e8e8; font-family:"{FONT}"; }}
QLabel#big {{ font-size:13px; font-weight:bold; }}
QLabel#sub {{ font-size:11px; color:#a8a8a8; }}
QLabel#ok {{ font-size:11px; color:#7ee2a8; }} QLabel#bad {{ font-size:11px; color:#ffb070; }}
QPushButton#fmt {{ min-width:0; padding:0; background:#333; border:1px solid #474747; border-radius:6px; font-weight:bold;
                  font-size:12px; min-height:28px; }}
QPushButton#fmt:hover {{ background:#0a84ff; border-color:#0a84ff; color:white; }}
QPushButton#act {{ background:#2f2f2f; border:1px solid #474747; border-radius:5px; font-size:11px; padding:3px 8px; min-height:22px; }}
QPushButton#act:hover {{ border-color:#0a84ff; background:#0a3d75; }}
QPushButton#cancel {{ background:#3a2323; border:1px solid #7a3a3a; border-radius:5px; font-size:11px; padding:2px 8px; color:#ffb3ad; }}
QPushButton#cancel:hover {{ background:#5a2a2a; }}
QPushButton#x {{ border:none; color:#aaa; font-size:14px; min-width:22px; max-width:22px; }}
QPushButton#x:hover {{ color:white; }}
QPushButton#edit {{ font-family:"Segoe Fluent Icons","Segoe MDL2 Assets"; font-size:11px; color:#cfcfcf;
                   border:1px solid #555; border-radius:5px; min-width:24px; max-width:24px; min-height:22px; max-height:22px; padding:0; }}
QPushButton#edit:hover {{ border-color:#0a84ff; color:white; background:#0a3d75; }}
QPushButton#rm {{ border:none; color:#777; font-size:10px; min-width:18px; max-width:18px; min-height:18px; }}
QPushButton#rm:hover {{ color:#ff7b72; }}
QPushButton#more {{ border:none; color:#4ea1ff; font-size:11px; text-align:left; padding:0; }}
QPushButton#more:hover {{ color:#8cc4ff; }}
QProgressBar {{ border:none; background:#333; max-height:5px; min-height:5px; border-radius:2px; }}
QProgressBar::chunk {{ background:#0a84ff; border-radius:2px; }}
QScrollArea {{ border:none; }}
QScrollBar:vertical {{ background:transparent; width:6px; }} QScrollBar::handle:vertical {{ background:#555; border-radius:3px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
"""


class Scanner(QThread):
    """后台扫描拖入的文件夹，显示进度，扫描完再让用户选格式。"""
    progress = pyqtSignal(int)
    done = pyqtSignal(list)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        out = []
        for p in self.paths:
            if os.path.isdir(p):
                for root, _, fs in os.walk(p):
                    out += [os.path.join(root, f) for f in fs]
                    self.progress.emit(len(out))
            elif os.path.isfile(p):
                out.append(p)
        self.done.emit(out)


class FloatBall(QWidget):
    def __init__(self, main):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.main = main
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setStyleSheet(QSS)
        self.mode = "bubble"
        self.files = []          # 待转换（或「下一批」）文件
        self.job = None          # 正在运行的 Worker
        self.job_done = 0
        self.last = None         # 上一批的结果摘要
        self.scanner = None
        self.scan_n = 0
        self.show_all = False
        self.drag_hot = False
        self.side = main.cfg.get("ball_side", "right")   # left / right / top
        self.pos_along = main.cfg.get("ball_pos")        # 沿边位置（左右为 y，顶部为 x）
        self.drag = None
        self._shape = 0.0    # 0 = 气泡 / 球，1 = 面板
        self._dock = 1.0     # 1 = 贴边（贴边一侧伸到屏幕外，呈半胶囊），0 = 悬空的完整圆形
        self.orb_logo = QPixmap(os.path.join(main.assets, "icon.png")).scaled(
            22, 22, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

        # ---- 等待拖入页
        self.page_drop = QWidget(self)
        v = QVBoxLayout(self.page_drop)
        v.setContentsMargins(10, 12, 10, 12)
        self.logo = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.logo.setPixmap(QPixmap(os.path.join(main.assets, "icon.png")).scaled(
            40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.drop_text = QLabel(objectName="big", alignment=Qt.AlignmentFlag.AlignCenter)
        self.drop_sub = QLabel(objectName="sub", alignment=Qt.AlignmentFlag.AlignCenter)
        self.drop_sub.setWordWrap(True)
        for w in (self.logo, self.drop_text, self.drop_sub):
            v.addWidget(w)

        # ---- 面板
        self.page_choose = QWidget(self)
        v = QVBoxLayout(self.page_choose)
        v.setContentsMargins(12, 10, 8, 12)
        v.setSpacing(6)
        head = QHBoxLayout()
        self.count = QLabel(objectName="big")
        head.addWidget(self.count, 1)
        self.btn_edit = QPushButton("", objectName="edit")   # 快速编辑常用 6 种格式
        self.btn_edit.clicked.connect(self.main.open_ball_settings)
        head.addWidget(self.btn_edit)
        self.btn_cancel = QPushButton(objectName="cancel")
        self.btn_cancel.clicked.connect(self.cancel_job)
        head.addWidget(self.btn_cancel)
        self.btn_x = QPushButton("✕", objectName="x")
        self.btn_x.clicked.connect(self.dismiss)
        head.addWidget(self.btn_x)
        v.addLayout(head)
        self.summary = QLabel(objectName="sub")
        self.summary.setWordWrap(True)
        v.addWidget(self.summary)
        self.bar = QProgressBar(textVisible=False)
        self.bar.setRange(0, 1000)
        v.addWidget(self.bar)
        self.acts = QWidget()
        ah = QHBoxLayout(self.acts)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.setSpacing(4)
        self.btn_open = QPushButton(objectName="act")
        self.btn_open.clicked.connect(self.open_output)
        self.btn_fail = QPushButton(objectName="act")
        self.btn_fail.clicked.connect(lambda: self.last and self.main.open_task(self.last["task"]))
        self.btn_retry = QPushButton(objectName="act")
        self.btn_retry.clicked.connect(self.retry_failed)
        for b in (self.btn_open, self.btn_fail, self.btn_retry):
            ah.addWidget(b)
        ah.addStretch()
        v.addWidget(self.acts)
        self.next_lbl = QLabel(objectName="sub")
        v.addWidget(self.next_lbl)
        self.names_box = QWidget()
        self.names = QVBoxLayout(self.names_box)   # 每个文件一行，右侧小 ✕ 可单独移除
        self.names.setSpacing(0)
        self.names.setContentsMargins(0, 0, 0, 0)
        self.names_area = QScrollArea()
        self.names_area.setWidgetResizable(True)
        self.names_area.setWidget(self.names_box)
        self.names_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        v.addWidget(self.names_area)
        self.btn_more = QPushButton(objectName="more")
        self.btn_more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_more.clicked.connect(self.toggle_all)
        v.addWidget(self.btn_more)
        self.grid_box = QWidget()
        self.grid = QGridLayout(self.grid_box)
        self.grid.setSpacing(6)
        self.grid.setContentsMargins(0, 4, 4, 0)
        v.addWidget(self.grid_box)
        self.status = QLabel(objectName="sub", alignment=Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        self.fx = QGraphicsOpacityEffect(self.page_choose)
        self.page_choose.setGraphicsEffect(self.fx)
        self.anim = QParallelAnimationGroup(self)
        self.geo_anim = QPropertyAnimation(self, b"geometry")
        self.geo_anim.setDuration(220)
        self.geo_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade = QPropertyAnimation(self.fx, b"opacity")
        self.fade.setDuration(260)
        self.shape_anim = QPropertyAnimation(self, b"shape")
        self.shape_anim.setDuration(240)
        self.shape_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.dock_anim = QPropertyAnimation(self, b"dock")
        self.dock_anim.setDuration(260)
        self.dock_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.addAnimation(self.geo_anim)
        self.anim.addAnimation(self.fade)
        self.anim.addAnimation(self.shape_anim)
        self.anim.addAnimation(self.dock_anim)
        self.bar_anim = QPropertyAnimation(self.bar, b"value", self)
        self.bar_anim.setDuration(350)

        self.leave_timer = QTimer(self, singleShot=True, interval=800, timeout=self.on_leave_timeout)
        # 屏幕插拔 / 分辨率变化：把气泡移回可见区域
        app = QGuiApplication.instance()
        for sig in (app.screenAdded, app.screenRemoved, app.primaryScreenChanged):
            sig.connect(self.on_screens)
        for scr in app.screens():
            scr.availableGeometryChanged.connect(self.on_screens)
        self.rebuild()

    # ================================================================ 动画属性
    def get_shape(self):
        return self._shape

    def set_shape(self, v):
        self._shape = v
        self.update()

    shape = pyqtProperty(float, get_shape, set_shape)

    def get_dock(self):
        return self._dock

    def set_dock(self, v):
        self._dock = v
        self.update()

    dock = pyqtProperty(float, get_dock, set_dock)

    # ================================================================ 文本 / 按钮
    def tr(self, s):
        return self.main.tr(s)

    def bubble_text(self):
        if self.job:
            return self.tr("转换中 {a}/{b}").format(a=self.job_done, b=len(self.job.files))
        if self.last:
            if self.last["failed"]:
                return self.tr("失败 {n}").format(n=self.last["failed"])
            return self.tr("完成 {n} 个").format(n=self.last["ok"])
        return self.tr("文件转换")

    def bubble_color(self):
        if self.last and not self.job:
            return AMBER if self.last["failed"] else GREEN
        return BLUE

    def rebuild(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        keys = []
        for key in self.main.cfg.get("ball_formats", [])[:6]:
            kind, fmt = key.split(":", 1)
            if kind == "preset":   # 转换预设：使用保存的格式与参数
                pr = self.main.preset_by_id(fmt)
                if not pr:
                    continue
                keys.append((pr["name"], pr["fmt"], pr["kind"], self.main.preset_params(pr), self.main.preset_desc(pr)))
            else:
                keys.append((fmt, fmt, kind, None, ""))
        for i, (label, fmt, kind, params, tip) in enumerate(keys):
            b = QPushButton(label, objectName="fmt")
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, f=fmt, k=kind, pa=params, lb=label: self.convert(f, k, pa, lb))
            self.grid.addWidget(b, i // 2, i % 2)
        self.n_fmt = len(keys)
        self.btn_edit.setToolTip(self.tr("编辑常用格式"))
        self.btn_cancel.setText(self.tr("取消任务"))
        self.btn_open.setText(self.tr("打开输出"))
        self.btn_fail.setText(self.tr("查看失败"))
        self.btn_retry.setText(self.tr("重试失败项"))
        self.refresh()
        self.apply_mode(self.mode, animate=False)

    def refresh(self):
        """按当前状态刷新面板内容。"""
        job, files, last = self.job, self.files, self.last
        n = len(files)
        # 标题
        if self.scanner:
            title = self.tr("正在扫描文件夹…")
        elif job:
            title = self.tr("正在转换 {n} 个").format(n=len(job.files))
            if n:
                title += " · " + self.tr("下一批 {n} 个").format(n=n)
        elif n:
            title = self.tr("已拖入 {n} 个文件").format(n=n)
        elif last:
            title = self.tr("完成 {n} 个").format(n=last["ok"])
            if last["failed"]:
                title += " · " + self.tr("失败 {n} 个").format(n=last["failed"])
        else:
            title = self.tr("拖入文件")
        self.count.setText(title)
        # 摘要
        if self.scanner:
            self.summary.setText(self.tr("已找到 {n} 个文件").format(n=self.scan_n))
        elif last and not job and n:
            self.summary.setText(self.tr("上一批：") + self.tr("完成 {n} 个").format(n=last["ok"]) +
                                 (" · " + self.tr("失败 {n} 个").format(n=last["failed"]) if last["failed"] else ""))
        else:
            self.summary.setText("")
        self.summary.setVisible(bool(self.summary.text()))
        self.bar.setVisible(bool(job))
        self.btn_cancel.setVisible(bool(job))
        self.btn_x.setVisible(not job and not self.scanner)
        self.btn_x.setToolTip(self.tr("清空文件") if n else self.tr("关闭结果"))
        show_acts = bool(last and not job)
        self.acts.setVisible(show_acts)
        if show_acts:
            self.btn_open.setVisible(bool(last["dir"]))
            self.btn_fail.setVisible(bool(last["failed"]))
            self.btn_retry.setVisible(bool(last["failed"]))
        self.next_lbl.setVisible(bool(job and n))
        self.next_lbl.setText(self.tr("下一批 {n} 个").format(n=n) + "：")
        # 文件列表
        while self.names.count():
            w = self.names.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)   # 立即移出，避免旧行残留并让高度重新计算
                w.deleteLater()
        shown = files if self.show_all else files[:4]
        width = self.choose_w()
        for f in shown:
            row = QWidget()
            row.setFixedHeight(ROW_H)
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 4, 0)
            lb = QLabel(objectName="sub")
            lb.setText(QFontMetrics(lb.font()).elidedText(os.path.basename(f), Qt.TextElideMode.ElideMiddle, width - 60))
            lb.setToolTip(f)
            h.addWidget(lb, 1)
            rm = QPushButton("✕", objectName="rm")
            rm.setToolTip(self.tr("移除"))
            rm.clicked.connect(lambda _, f=f: self.remove_file(f))
            h.addWidget(rm)
            self.names.addWidget(row)
            row.show()  # 新行需显式显示，否则计算高度时被忽略
        self.names_area.setVisible(bool(shown))
        self.names_area.setFixedHeight(min(len(shown), 10) * ROW_H + (2 if shown else 0))
        self.btn_more.setVisible(n > 4)
        self.btn_more.setText(self.tr("收起 ▴") if self.show_all else self.tr("还有 {n} 个 ▸").format(n=n - 4))
        # 格式按钮
        choose = bool(n and not job and not self.scanner)
        self.grid_box.setVisible(choose)
        for b in self.grid_box.findChildren(QPushButton):
            b.setEnabled(choose)
        if self.scanner:
            self.status.setText("")
        elif job and n:
            self.status.setText(self.tr("下一批将在当前任务完成后选择格式"))
        elif job:
            self.status.setText("")
        elif choose:
            self.status.setText(self.tr("选择要转换成的格式") if self.n_fmt else self.tr("右键设置常用格式"))
        else:
            self.status.setText("")
        self.status.setVisible(bool(self.status.text()))
        self.update()

    # 兼容旧调用
    refresh_files = refresh

    # ================================================================ 几何
    def screen_rect(self):
        scr = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        return scr.availableGeometry()

    def upright(self):
        """左右两侧时，中文逐字竖排（字是正的）；英文与数字整体旋转 90°。"""
        return self.side != "top" and all(ord(ch) > 0x2E80 for ch in self.bubble_text())

    def bubble_size(self):
        fm = QFontMetrics(QFont(FONT, 9), self)
        t = self.bubble_text()
        if self.upright():
            return QSize(BUBBLE_T, fm.height() * len(t) + 14)  # 文字变长气泡跟着变长
        tw = fm.horizontalAdvance(t) + 22
        return QSize(tw, BUBBLE_T) if self.side == "top" else QSize(BUBBLE_T, tw)

    def panel_size(self, mode):
        if mode == "drop":
            return DROP_SIZE
        w = self.choose_w()
        self.page_choose.setFixedWidth(w)
        lay = self.page_choose.layout()
        lay.invalidate()
        lay.activate()
        h = lay.heightForWidth(w) if lay.hasHeightForWidth() else lay.sizeHint().height()
        return QSize(w, max(h, 90))

    def choose_w(self):
        """宽度随标题文字变化（英文更长），按钮不会被挤压。"""
        self.count.ensurePolished()
        fm = QFontMetrics(self.count.font())
        extra = 130 if self.job else 95   # 标题右侧的 ✎、✕ / 取消任务
        need = fm.horizontalAdvance(self.count.text()) + extra + 20
        return max(CHOOSE_W, min(need, 340))

    def rect_for(self, mode):
        if mode == "orb":
            c = QCursor.pos() - (self.drag[3] if self.drag and len(self.drag) > 3 else QPoint(0, 0))
            return QRect(c.x() - ORB // 2, c.y() - ORB // 2, ORB, ORB)
        r = self.screen_rect()
        s = self.bubble_size() if mode == "bubble" else self.panel_size(mode)
        if self.side == "top":
            c = self.pos_along if self.pos_along is not None else r.center().x()
            x = max(r.left(), min(c - s.width() // 2, r.right() - s.width()))
            return QRect(x, r.top(), s.width(), s.height())
        c = self.pos_along if self.pos_along is not None else r.top() + r.height() // 3
        y = max(r.top(), min(c - s.height() // 2, r.bottom() - s.height()))
        x = r.right() - s.width() + 1 if self.side == "right" else r.left()
        return QRect(x, y, s.width(), s.height())

    def on_screens(self, *_):
        for scr in QGuiApplication.screens():
            try:
                scr.availableGeometryChanged.disconnect(self.on_screens)
            except TypeError:
                pass
            scr.availableGeometryChanged.connect(self.on_screens)
        QTimer.singleShot(300, lambda: self.apply_mode(self.mode, animate=False))

    # ================================================================ 阶段切换
    def apply_mode(self, mode, animate=True):
        old = self.mode
        self.mode = mode
        self.page_drop.setVisible(mode == "drop")
        self.page_choose.setVisible(mode == "panel")
        target = self.rect_for(mode)
        for p in (self.page_drop, self.page_choose):
            p.setGeometry(0, 0, target.width(), target.height())
        self.anim.stop()
        shape_to = 1.0 if mode in ("drop", "panel") else 0.0
        dock_to = 1.0 if mode == "bubble" else 0.0
        if animate and self.isVisible():
            self.geo_anim.setStartValue(self.geometry())
            self.geo_anim.setEndValue(target)
            self.fade.setStartValue(0.0 if (mode == "panel" and old != "panel") else 1.0)
            self.fade.setEndValue(1.0)
            self.shape_anim.setStartValue(self._shape)
            self.shape_anim.setEndValue(shape_to)
            self.dock_anim.setStartValue(self._dock)
            self.dock_anim.setEndValue(dock_to)
            for a in (self.geo_anim, self.shape_anim, self.dock_anim):
                a.setDuration(320 if mode == "bubble" and old == "orb" else 240)
            self.anim.start()
        else:
            self.fx.setOpacity(1.0)
            self._shape, self._dock = shape_to, dock_to
            self.setGeometry(target)
        self.update()

    def has_panel(self):
        return bool(self.files or self.job or self.last or self.scanner)

    def expand(self):
        self.leave_timer.stop()
        if self.mode == "bubble":
            self.refresh()
            self.apply_mode("panel" if self.has_panel() else "drop")

    def collapse(self):
        if self.mode != "bubble":
            self.apply_mode("bubble")

    def relayout(self):
        self.refresh()
        if self.mode != "bubble":
            self.apply_mode("panel" if self.has_panel() else "drop")
        else:
            self.apply_mode("bubble", animate=False)

    def remove_file(self, f):
        if f in self.files:
            self.files.remove(f)
        if len(self.files) <= 4:
            self.show_all = False
        self.relayout()

    def toggle_all(self):
        self.show_all = not self.show_all
        self.relayout()

    def dismiss(self):
        """✕：有待转换文件时清空它们；否则关闭上一批的结果。"""
        if self.files:
            self.files = []
            self.show_all = False
        else:
            self.last = None
        self.relayout()

    # 兼容旧调用
    def reset(self):
        self.files, self.last, self.show_all = [], None, False
        self.relayout()

    def on_leave_timeout(self):
        if self.drag or self.scanner or self.mode == "orb" or self.geometry().contains(QCursor.pos()):
            self.leave_timer.start(800)
            return
        self.collapse()

    # ================================================================ 绘制
    @staticmethod
    def _mix(a, b, t):
        return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                      int(a.blue() + (b.blue() - a.blue()) * t), int(a.alpha() + (b.alpha() - a.alpha()) * t))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0, 0, self.width(), self.height())
        t, dk = self._shape, self._dock
        rad = min(r.width(), r.height()) / 2 * (1 - t) + 12 * t     # 圆 / 胶囊 → 圆角面板
        # 贴边时，靠边一侧伸到屏幕外，只露出圆润的一侧；悬空（拖动中）时是完整的圆
        ext = rad * dk * (1 - t)
        rr = QRectF(r)
        if self.side == "right":
            rr.adjust(0, 0, ext, 0)
        elif self.side == "left":
            rr.adjust(-ext, 0, 0, 0)
        else:
            rr.adjust(0, -ext, 0, 0)
        hot = self.drag_hot and self.mode in ("drop", "panel")
        bg = QColor(10, 60, 117, 235) if hot else PANEL_BG
        p.setBrush(self._mix(self.bubble_color(), bg, t))
        if t > 0.5:
            p.setPen(QPen(QColor(10, 132, 255), 2, Qt.PenStyle.DashLine) if hot else QColor(70, 70, 70))
        else:
            p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rr.adjusted(1, 1, -1, -1), rad, rad)
        if t >= 0.35:
            return
        # 气泡 / 球上的内容，在变形过程中淡出
        p.setOpacity(1 - t / 0.35)
        if self.mode == "orb":
            self.paint_orb(p, r)
            return
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont(FONT, 9))
        txt = self.bubble_text()
        ri = r.toRect()
        if self.side == "top":
            p.drawText(ri, Qt.AlignmentFlag.AlignCenter, txt)
        elif self.upright():
            fh = QFontMetrics(p.font()).height()
            y0 = (ri.height() - fh * len(txt)) // 2
            for i, ch in enumerate(txt):
                p.drawText(QRect(0, y0 + i * fh, ri.width(), fh), Qt.AlignmentFlag.AlignCenter, ch)
        else:  # 左右两侧竖排显示
            p.translate(r.center())
            p.rotate(90 if self.side == "right" else -90)
            p.drawText(QRect(-ri.height() // 2, -ri.width() // 2, ri.height(), ri.width()), Qt.AlignmentFlag.AlignCenter, txt)

    def paint_orb(self, p, r):
        """拖动中的球：显示工作状态——转换进度环、完成 ✓ / 失败数，空闲时显示图标。"""
        c = r.center()
        if self.job:
            n = max(len(self.job.files), 1)
            ring = r.adjusted(4, 4, -4, -4)
            p.setPen(QPen(QColor(255, 255, 255, 70), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(ring)
            p.setPen(QPen(QColor(255, 255, 255), 3, cap=Qt.PenCapStyle.RoundCap))
            p.drawArc(ring, 90 * 16, -int(360 * 16 * self.job_done / n))
            p.setFont(QFont(FONT, 8, QFont.Weight.Bold))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, f"{self.job_done}/{len(self.job.files)}")
        elif self.last:
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont(FONT, 13 if not self.last["failed"] else 11, QFont.Weight.Bold))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "✓" if not self.last["failed"] else f"!{self.last['failed']}")
        elif self.files:
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont(FONT, 11, QFont.Weight.Bold))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(len(self.files)))
        else:
            p.drawPixmap(int(c.x() - self.orb_logo.width() / 2), int(c.y() - self.orb_logo.height() / 2), self.orb_logo)

    def set_hot(self, on):
        """拖着文件靠近时高亮投放区。"""
        self.drag_hot = on
        self.drop_text.setText(self.tr("松开以添加文件") if on else self.tr("拖入文件"))
        self.drop_sub.setText("" if on else (self.tr("松开后选择目标格式") if self.n_fmt else self.tr("右键设置常用格式")))
        self.update()

    # ================================================================ 鼠标 / 拖放
    def enterEvent(self, e):
        self.leave_timer.stop()
        if self.mode == "bubble":
            self.setToolTip(self.tr("点击展开"))

    def leaveEvent(self, e):
        if self.mode != "bubble":
            self.leave_timer.start(900)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.expand()
            self.set_hot(True)

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.set_hot(False)
        self.leave_timer.start(900)

    def dropEvent(self, e):
        self.set_hot(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls()]
        if any(os.path.isdir(p) for p in paths):
            if self.scanner:
                return
            self.scan_n = 0
            self.scanner = Scanner(paths)
            self.scanner.progress.connect(self.on_scan)
            self.scanner.done.connect(self.scan_done)
            self.scanner.start()
            self.relayout()
            return
        self.add([p for p in paths if os.path.isfile(p)])

    def on_scan(self, n):
        self.scan_n = n
        self.summary.setText(self.tr("已找到 {n} 个文件").format(n=n))

    def scan_done(self, files):
        self.scanner.wait()
        self.scanner = None
        self.add(files)
        self.relayout()

    def add(self, new):
        if not self.job:
            self.last = None   # 新的一批开始，旧结果收起（任务面板里仍可查看）
        self.files += [f for f in new if f not in self.files]
        self.relayout()
        self.activateWindow()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag = (e.globalPosition().toPoint(), self.pos(), False)

    def mouseMoveEvent(self, e):
        if not self.drag or self.main.cfg.get("ball_locked"):
            return
        start, pos0, moved = self.drag[:3]
        d = e.globalPosition().toPoint() - start
        if not moved and d.manhattanLength() <= 6:
            return
        if not moved:   # 开始拖动：平滑变成显示工作状态的球
            self.drag = (start, pos0, True, QPoint(0, 0))
            self.leave_timer.stop()
            self.apply_mode("orb")
            return
        target = self.rect_for("orb")
        if self.anim.state() == QParallelAnimationGroup.State.Running:
            self.geo_anim.setEndValue(target)   # 变形动画进行中，终点跟着鼠标走
        else:
            self.setGeometry(target)

    def mouseReleaseEvent(self, e):
        if not self.drag:
            return
        moved = self.drag[2]
        self.drag = None
        if not moved:   # 单击：气泡展开；空白投放区打开主窗口
            if self.mode == "bubble":
                self.expand()
            elif self.mode == "drop":
                self.main.show_main()
            return
        # 吸附到最近的边：左 / 右 / 顶，球平滑变成贴边胶囊
        self.anim.stop()
        self.setGeometry(self.rect_for("orb"))
        r, c = self.screen_rect(), self.geometry().center()
        dist = {"left": c.x() - r.left(), "right": r.right() - c.x(), "top": c.y() - r.top()}
        self.side = min(dist, key=dist.get)
        self.pos_along = c.x() if self.side == "top" else c.y()
        self.main.cfg.update(ball_side=self.side, ball_pos=self.pos_along)
        self.main.save()
        self.apply_mode("bubble")

    def toggle_lock(self, on):
        self.main.cfg["ball_locked"] = on
        self.main.save()

    def reset_pos(self):
        self.side, self.pos_along = "right", None
        self.main.cfg.update(ball_side="right", ball_pos=None)
        self.main.save()
        self.apply_mode(self.mode)

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.setStyleSheet("QMenu{background:#2b2b2b;color:#eee;border:1px solid #444}"
                        "QMenu::item{padding:6px 18px}QMenu::item:selected{background:#0a84ff}")
        m.addAction(self.tr("打开主窗口"), self.main.show_main)
        m.addAction(self.tr("查看任务"), self.main.open_tasks)
        m.addAction(self.tr("常用格式…"), self.main.open_ball_settings)
        m.addAction(self.tr("打开输出文件夹"), self.main.open_out)
        m.addSeparator()
        a = m.addAction(self.tr("锁定位置"))
        a.setCheckable(True)
        a.setChecked(bool(self.main.cfg.get("ball_locked")))
        a.toggled.connect(self.toggle_lock)
        m.addAction(self.tr("重置位置"), self.reset_pos)
        m.addSeparator()
        m.addAction(self.tr("退出"), self.main.quit_app)
        m.exec(e.globalPos())

    # ================================================================ 转换
    def convert(self, fmt, kind, params=None, label=None):
        if not self.files or self.job:
            return
        files, self.files, self.show_all, self.last = list(self.files), [], False, None
        self.job_done = 0
        self.bar_anim.stop()
        self.bar.setValue(0)
        self.job = self.main.run_job(files, fmt, kind, self.done, auto_open=bool(self.main.cfg.get("ball_auto_open")),
                                     params=params, label=label)
        self.job.file_done.connect(self.on_file)
        self.relayout()

    def on_file(self, i, info):
        if self.mode == "orb":
            self.update()
        if not self.job:
            return
        self.job_done = i + 1
        self.bar_anim.stop()
        self.bar_anim.setStartValue(self.bar.value())
        self.bar_anim.setEndValue(int(1000 * self.job_done / max(len(self.job.files), 1)))
        self.bar_anim.start()
        if self.mode == "bubble":
            self.apply_mode("bubble", animate=False)   # 气泡上的「转换中 a/b」随进度更新
        else:
            self.count.setText(self.count.text())

    def cancel_job(self):
        if self.job:
            self.main.cancel_task(self.job.task)

    def done(self, task, ok, bad):
        rs = [r for r in task["results"] if r]
        self.last = {"task": task, "ok": sum(1 for r in rs if r["state"] in ("full", "partial", "preview")),
                     "failed": sum(1 for r in rs if r["state"] in ("failed", "cancelled")) +
                               sum(1 for r in task["results"] if r is None),
                     "dir": os.path.dirname(ok[0]) if ok else None}
        self.job = None
        self.relayout()
        if self.mode != "bubble" and not self.geometry().contains(QCursor.pos()):
            self.leave_timer.start(4000)   # 结果面板自动收起，气泡保留状态，点一下就能找回

    def open_output(self):
        if self.last and self.last["dir"]:
            os.startfile(self.last["dir"])
        else:
            self.main.open_out()

    def retry_failed(self):
        if not self.last or self.job:
            return
        t = self.last["task"]
        failed = [r["src"] for r in t["results"] if r and r["state"] in ("failed", "cancelled")]
        failed += [f for f, r in zip(t["files"], t["results"]) if r is None]
        if failed:
            pending, expanded = self.files, self.show_all
            self.files = failed
            self.convert(t["fmt"], t["kind"], t["params"] or None, t["label"])
            self.files, self.show_all = pending, expanded
            self.relayout()
