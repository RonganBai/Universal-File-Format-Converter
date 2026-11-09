"""屏幕边缘悬浮窗。

阶段：
  bubble  收起：贴边的小气泡（背景 75% 不透明），显示「文件转换」，可吸附在左 / 右 / 顶部
  drop    展开：等待拖入文件（不显示格式按钮）
  choose  已收到文件：显示文件名与数量，等待选择格式（带切换动画）
  busy / done  转换中 / 完成，完成后自动打开输出文件夹并收回
"""
import os

from PyQt6.QtCore import (Qt, QTimer, QPropertyAnimation, QParallelAnimationGroup, QPoint, QRect,
                          QEasingCurve, QSize)
from PyQt6.QtGui import QPainter, QColor, QPixmap, QGuiApplication, QCursor, QFont, QFontMetrics
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel, QMenu,
                             QGraphicsOpacityEffect)

BUBBLE_T = 22      # 气泡厚度（贴边方向的尺寸）
DROP_SIZE = QSize(150, 128)
CHOOSE_W = 210
FONT = "Microsoft YaHei UI"

QSS = f"""
QWidget {{ background:transparent; color:#e8e8e8; font-family:"{FONT}"; }}
QLabel#big {{ font-size:13px; font-weight:bold; }}
QLabel#sub {{ font-size:11px; color:#a8a8a8; }}
QPushButton#fmt {{ min-width:0; padding:0; background:#333; border:1px solid #474747; border-radius:6px; font-weight:bold;
                  font-size:12px; min-height:28px; }}
QPushButton#fmt:hover {{ background:#0a84ff; border-color:#0a84ff; color:white; }}
QPushButton#x {{ border:none; color:#aaa; font-size:14px; min-width:22px; max-width:22px; }}
QPushButton#x:hover {{ color:white; }}
"""


class FloatBall(QWidget):
    def __init__(self, main):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.main = main
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setStyleSheet(QSS)
        self.mode = "bubble"
        self.files = []
        self.busy = False
        self.side = main.cfg.get("ball_side", "right")   # left / right / top
        self.pos_along = main.cfg.get("ball_pos")        # 沿边位置（左右为 y，顶部为 x）
        self.drag = None

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

        # ---- 选择格式页
        self.page_choose = QWidget(self)
        v = QVBoxLayout(self.page_choose)
        v.setContentsMargins(12, 10, 8, 12)
        v.setSpacing(6)
        head = QHBoxLayout()
        self.count = QLabel(objectName="big")
        head.addWidget(self.count, 1)
        self.btn_x = QPushButton("✕", objectName="x")
        self.btn_x.clicked.connect(self.reset)
        head.addWidget(self.btn_x)
        v.addLayout(head)
        self.names = QLabel(objectName="sub")
        self.names.setWordWrap(True)
        v.addWidget(self.names)
        self.grid = QGridLayout()
        self.grid.setSpacing(6)
        self.grid.setContentsMargins(0, 4, 4, 0)
        v.addLayout(self.grid)
        self.status = QLabel(objectName="sub", alignment=Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.status)

        self.fx = QGraphicsOpacityEffect(self.page_choose)
        self.page_choose.setGraphicsEffect(self.fx)
        self.anim = QParallelAnimationGroup(self)
        self.geo_anim = QPropertyAnimation(self, b"geometry")
        self.geo_anim.setDuration(220)
        self.geo_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade = QPropertyAnimation(self.fx, b"opacity")
        self.fade.setDuration(260)
        self.anim.addAnimation(self.geo_anim)
        self.anim.addAnimation(self.fade)

        self.leave_timer = QTimer(self, singleShot=True, interval=800, timeout=self.on_leave_timeout)
        self.rebuild()

    # ================================================================ 文本 / 按钮
    def tr(self, s):
        return self.main.tr(s)

    def bubble_text(self):
        return self.tr("文件转换")

    def rebuild(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        keys = self.main.cfg.get("ball_formats", [])[:6]
        for i, key in enumerate(keys):
            kind, fmt = key.split(":", 1)
            b = QPushButton(fmt, objectName="fmt")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, f=fmt, k=kind: self.convert(f, k))
            self.grid.addWidget(b, i // 2, i % 2)
        self.n_fmt = len(keys)
        self.drop_text.setText(self.tr("拖入文件"))
        self.drop_sub.setText(self.tr("松开后选择目标格式") if keys else self.tr("右键设置常用格式"))
        self.refresh_files()
        self.apply_mode(self.mode, animate=False)

    def refresh_files(self):
        n = len(self.files)
        self.count.setText(self.tr("已拖入 {n} 个文件").format(n=n))
        shown = [os.path.basename(f) for f in self.files[:3]]
        fm = QFontMetrics(self.names.font())
        shown = [fm.elidedText(s, Qt.TextElideMode.ElideMiddle, CHOOSE_W - 30) for s in shown]
        if n > 3:
            shown.append(self.tr("…等 {n} 个").format(n=n))
        self.names.setText("\n".join(shown))
        if not self.busy:
            self.status.setText(self.tr("选择要转换成的格式") if self.n_fmt else self.tr("右键设置常用格式"))

    # ================================================================ 几何
    def screen_rect(self):
        scr = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        return scr.availableGeometry()

    def upright(self):
        """左右两侧时，中文逐字竖排（字是正的）；英文整体旋转 90°。"""
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
        self.page_choose.setFixedWidth(CHOOSE_W)
        self.page_choose.adjustSize()
        h = self.page_choose.layout().sizeHint().height()
        return QSize(CHOOSE_W, max(h, 120))

    def rect_for(self, mode):
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

    # ================================================================ 阶段切换
    def apply_mode(self, mode, animate=True):
        old = self.mode
        self.mode = mode
        self.page_drop.setVisible(mode == "drop")
        self.page_choose.setVisible(mode in ("choose", "busy", "done"))
        target = self.rect_for(mode)
        for p in (self.page_drop, self.page_choose):
            p.setGeometry(0, 0, target.width(), target.height())
        self.anim.stop()
        if animate and self.isVisible():
            self.geo_anim.setStartValue(self.geometry())
            self.geo_anim.setEndValue(target)
            entering_choose = mode == "choose" and old != "choose"
            self.fade.setStartValue(0.0 if entering_choose else 1.0)
            self.fade.setEndValue(1.0)
            self.anim.start()
        else:
            self.fx.setOpacity(1.0)
            self.setGeometry(target)
        for b in self.page_choose.findChildren(QPushButton):
            b.setEnabled(mode == "choose" or b is self.btn_x)
        self.update()

    def expand(self):
        self.leave_timer.stop()
        if self.mode == "bubble":
            self.apply_mode("choose" if self.files else "drop")

    def collapse(self):
        if self.mode != "bubble":
            self.apply_mode("bubble")

    def reset(self):
        self.files = []
        self.refresh_files()
        self.apply_mode("drop")

    def on_leave_timeout(self):
        if self.drag or self.busy or self.geometry().contains(QCursor.pos()):
            self.leave_timer.start(800)
            return
        if self.mode == "done":
            self.files = []
            self.refresh_files()
        self.collapse()

    # ================================================================ 绘制
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRect(0, 0, self.width(), self.height())
        if self.mode == "bubble":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(10, 110, 230, 191))  # 75% 不透明
            rad = BUBBLE_T / 2
            # 贴边那一侧延伸到屏幕外，只露出圆润的一侧
            if self.side == "right":
                rr = r.adjusted(0, 0, int(rad), 0)
            elif self.side == "left":
                rr = r.adjusted(-int(rad), 0, 0, 0)
            else:
                rr = r.adjusted(0, -int(rad), 0, 0)
            p.drawRoundedRect(rr, rad, rad)
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont(FONT, 9))
            if self.side == "top":
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.bubble_text())
            elif self.upright():
                fh = QFontMetrics(p.font()).height()
                y0 = (r.height() - fh * len(self.bubble_text())) // 2
                for i, ch in enumerate(self.bubble_text()):
                    p.drawText(QRect(0, y0 + i * fh, r.width(), fh), Qt.AlignmentFlag.AlignCenter, ch)
            else:  # 左右两侧竖排显示
                p.translate(r.center())
                p.rotate(90 if self.side == "right" else -90)
                p.drawText(QRect(-r.height() // 2, -r.width() // 2, r.height(), r.width()),
                           Qt.AlignmentFlag.AlignCenter, self.bubble_text())
            return
        p.setPen(QColor(70, 70, 70))
        p.setBrush(QColor(31, 31, 31, 240))
        p.drawRoundedRect(r.adjusted(0, 0, -1, -1), 12, 12)

    # ================================================================ 鼠标 / 拖放
    def enterEvent(self, e):
        self.expand()

    def leaveEvent(self, e):
        self.leave_timer.start(800)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.expand()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.leave_timer.start(800)

    def dropEvent(self, e):
        new = []
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if os.path.isdir(p):
                for root, _, fs in os.walk(p):
                    new += [os.path.join(root, f) for f in fs]
            elif os.path.isfile(p):
                new.append(p)
        if self.mode == "done":
            self.files = []
        self.files += [f for f in new if f not in self.files]
        if not self.files:
            return
        self.busy = False
        self.refresh_files()
        self.apply_mode("choose")
        self.activateWindow()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag = (e.globalPosition().toPoint(), self.pos(), False)

    def mouseMoveEvent(self, e):
        if not self.drag:
            return
        start, pos0, moved = self.drag
        d = e.globalPosition().toPoint() - start
        if moved or d.manhattanLength() > 6:
            self.drag = (start, pos0, True)
            self.anim.stop()
            self.move(pos0 + d)

    def mouseReleaseEvent(self, e):
        if not self.drag:
            return
        moved = self.drag[2]
        self.drag = None
        if not moved:
            if self.mode == "drop":
                self.main.show_main()
            return
        # 吸附到最近的边：左 / 右 / 顶
        r, c = self.screen_rect(), self.geometry().center()
        dist = {"left": c.x() - r.left(), "right": r.right() - c.x(), "top": c.y() - r.top()}
        self.side = min(dist, key=dist.get)
        self.pos_along = c.x() if self.side == "top" else c.y()
        self.main.cfg.update(ball_side=self.side, ball_pos=self.pos_along)
        self.main.save()
        self.apply_mode(self.mode)

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.setStyleSheet("QMenu{background:#2b2b2b;color:#eee;border:1px solid #444}"
                        "QMenu::item{padding:6px 18px}QMenu::item:selected{background:#0a84ff}")
        m.addAction(self.tr("打开主窗口"), self.main.show_main)
        m.addAction(self.tr("悬浮球设置…"), self.main.open_ball_settings)
        m.addAction(self.tr("打开输出文件夹"), self.main.open_out)
        m.addSeparator()
        m.addAction(self.tr("退出"), self.main.quit_app)
        m.exec(e.globalPos())

    # ================================================================ 转换
    def convert(self, fmt, kind):
        if not self.files or self.busy:
            return
        self.busy = True
        self.status.setText(self.tr("正在转换为 {f}…").format(f=fmt))
        self.apply_mode("busy", animate=False)
        self.main.run_job(list(self.files), fmt, kind, self.done, auto_open=True)

    def done(self, ok, bad):
        self.busy = False
        msg = self.tr("完成 {n} 个").format(n=len(ok))
        if bad:
            msg += "，" + self.tr("失败 {n} 个").format(n=len(bad))
            self.setToolTip("\n".join(bad))
        self.status.setText(msg)
        self.apply_mode("done", animate=False)
        self.leave_timer.start(2500)
