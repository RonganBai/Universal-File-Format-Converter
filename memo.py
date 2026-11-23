"""备忘录：便签数据（自动保存）、可插图的便签编辑器与桌面便签小窗（最多同时 3 个）。

与文件转换完全分开：只依赖主窗口提供的 tr()、theme_colors() 和配置保存，不引用任何转换代码。
"""
import json
import os
import re
import time
import uuid

from PyQt6.QtCore import QObject, QPoint, QRect, QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (QColor, QGuiApplication, QImage, QKeySequence, QPainter, QPen, QShortcut, QTextCursor,
                         QTextDocument,
                         QTextFormat, QTextImageFormat, QTextLength)
from PyQt6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QSizePolicy, QSizeGrip,
                             QTextEdit, QVBoxLayout, QWidget)

MAX_NOTES = 2000
MAX_FLOATS = 3            # 便签小窗里最多同时显示的便签数
MAX_IMG_SIDE = 1600       # 导入的图片最长边超过它就先缩小再保存，避免便签目录越来越大
IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")
_SRC = re.compile(r'<img[^>]*?src="([^"]+)"', re.I)


def note_title(note, empty="空白便签"):
    """自定义标题优先；否则取首个非空行。"""
    t = (note.get("title") or "").strip()
    if t:
        return t[:40] + ("…" if len(t) > 40 else "")
    for line in note.get("text", "").splitlines():
        line = line.replace("￼", "").strip()
        if line:
            return line[:40] + ("…" if len(line) > 40 else "")
    return empty


def when(ts, today_word="今天"):
    lt = time.localtime(ts)
    if time.strftime("%Y-%m-%d", lt) == time.strftime("%Y-%m-%d"):
        return f"{today_word} {time.strftime('%H:%M', lt)}"
    return time.strftime("%Y-%m-%d %H:%M", lt)


def edge_color(t):
    """悬浮窗描边：主题强调色压暗，深浅模式都清楚可见。"""
    return QColor(t["accent"]).darker(150)


def image_count(note):
    return len(_SRC.findall(note.get("html", "")))


class MemoStore(QObject):
    """便签存储：内存中修改，停止输入 0.5 秒后写盘（先写临时文件再替换，避免写到一半损坏）。
    图片单独存在 memos.json 旁边的 memo_images 文件夹，便签里只记文件名。"""
    changed = pyqtSignal(str, object)   # (便签 id，"" 表示列表变化；发起修改的对象)

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.img_dir = os.path.join(os.path.dirname(path), "memo_images")
        self.notes = []
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.notes = [n for n in data.get("notes", []) if isinstance(n, dict) and "id" in n]
        except Exception:
            self.notes = []
        self._timer = QTimer(self, singleShot=True, interval=500, timeout=self.flush)
        self._dirty = False
        QTimer.singleShot(5000, self.clean_images)

    # ---- 读取
    def sorted(self, query=""):
        q = query.strip().lower()
        ns = [n for n in self.notes
              if not q or q in n.get("text", "").lower() or q in (n.get("title") or "").lower()]
        return sorted(ns, key=lambda n: (not n.get("pinned"), -n.get("updated", 0)))

    def get(self, nid):
        return next((n for n in self.notes if n["id"] == nid), None)

    # ---- 修改
    def new(self, text="", source=None):
        now = time.time()
        n = {"id": uuid.uuid4().hex[:12], "text": text, "created": now, "updated": now, "pinned": False}
        self.notes.append(n)
        del self.notes[:-MAX_NOTES]
        self._touch("", source)
        return n

    def set_text(self, nid, text, source=None):
        self.set_content(nid, None, text, source)

    def set_content(self, nid, html, text, source=None):
        """html 为 None 表示纯文字便签。text 始终保存一份纯文字，用于搜索和自动标题。"""
        n = self.get(nid)
        if n is None or (n.get("text") == text and n.get("html") == html):
            return
        n["text"] = text
        if html is None:
            n.pop("html", None)
        else:
            n["html"] = html
        n["updated"] = time.time()
        self._touch(nid, source)

    def set_title(self, nid, title, source=None):
        n = self.get(nid)
        title = (title or "").strip()[:80]
        if n is None or (n.get("title") or "") == title:
            return
        if title:
            n["title"] = title
        else:
            n.pop("title", None)
        n["updated"] = time.time()
        self._touch("", source)          # 标题会影响列表排序和显示，按列表变化通知

    def set_pinned(self, nid, on, source=None):
        n = self.get(nid)
        if n is not None:
            n["pinned"] = bool(on)
            self._touch("", source)

    def delete(self, nid, source=None):
        gone = self.get(nid)
        self.notes = [n for n in self.notes if n["id"] != nid]
        if gone and gone.get("html"):
            self.clean_images(set(_SRC.findall(gone["html"])))
        self._touch("", source)

    def _touch(self, nid, source):
        self._dirty = True
        self._timer.start()
        self.changed.emit(nid, source)

    def flush(self):
        if not self._dirty:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 2, "notes": self.notes}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)
        self._dirty = False

    # ---- 图片
    def save_image(self, img):
        """把 QImage 存进图片目录，返回文件名；过大的图先缩小。"""
        if img.isNull():
            return None
        if max(img.width(), img.height()) > MAX_IMG_SIDE:
            img = img.scaled(MAX_IMG_SIDE, MAX_IMG_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        os.makedirs(self.img_dir, exist_ok=True)
        alpha = img.hasAlphaChannel()
        name = uuid.uuid4().hex[:16] + (".png" if alpha else ".jpg")
        if not img.save(os.path.join(self.img_dir, name), "PNG" if alpha else "JPG", -1 if alpha else 90):
            return None
        return name

    def clean_images(self, only=None):
        """删掉没有任何便签引用的图片（only 给定时只检查这些文件）。"""
        try:
            names = only if only is not None else set(os.listdir(self.img_dir))
        except OSError:
            return
        used = set()
        for n in self.notes:
            used.update(_SRC.findall(n.get("html", "")))
        for name in names - used:
            p = os.path.join(self.img_dir, os.path.basename(name))
            try:
                if os.path.isfile(p) and time.time() - os.path.getmtime(p) > (0 if only is not None else 60):
                    os.remove(p)
            except OSError:
                pass


class NoteEdit(QTextEdit):
    """便签编辑器：纯文字粘贴（不带网页颜色字体），支持粘贴 / 拖入 / 选择图片；
    拖动图片右边缘调整大小，右键图片有常用尺寸，Ctrl+滚轮也可缩放。"""
    edited = pyqtSignal()
    EDGE = 8

    def __init__(self, store, tr, parent=None):
        super().__init__(parent)
        self.store, self._tr = store, tr
        self.setAcceptRichText(False)
        self.setTabChangesFocus(False)
        self.document().setDocumentMargin(4)
        self.viewport().setMouseTracking(True)
        self._resize = None          # (图片位置, 起点 x, 宽高比)
        self._sel = None             # 选中的图片位置（画一个框和拖动手柄）
        self.textChanged.connect(self._changed)

    # ---- 内容进出
    def load(self, note):
        self.blockSignals(True)
        self._sel = None
        if note and note.get("html"):
            self.setHtml(note["html"])
        else:
            self.setPlainText(note.get("text", "") if note else "")
        self._fit_images()
        self.blockSignals(False)

    def _fit_images(self):
        """图片最多显示为编辑区宽度：主窗口里插的大图放进窄小窗也不会撑出横向滚动条（保存的尺寸不变）。"""
        doc = self.document()
        doc.setUndoRedoEnabled(False)
        for p, ch in enumerate(doc.toPlainText()):
            if ch == "￼":
                c = QTextCursor(doc)
                c.setPosition(p)
                c.setPosition(p + 1, QTextCursor.MoveMode.KeepAnchor)
                if c.charFormat().isImageFormat():
                    c.setCharFormat(self._fmt(c.charFormat().toImageFormat()))
        doc.setUndoRedoEnabled(True)

    @staticmethod
    def _fmt(fmt, w=None):
        """只记宽度（高度按原图比例自动算），并限制最多占满编辑区宽度。"""
        f = QTextImageFormat(fmt)
        if w is not None:
            f.setWidth(w)
        f.clearProperty(QTextFormat.Property.ImageHeight)
        f.setMaximumWidth(QTextLength(QTextLength.Type.PercentageLength, 100))
        return f

    def content(self):
        """返回 (html 或 None, 纯文字)。没有图片时只存纯文字，便签文件更小。"""
        text = self.toPlainText().replace("￼", "")
        html = self.toHtml()
        if "<img" not in html:
            return None, text
        return re.sub(r"<body[^>]*>", "<body>", html, count=1), text   # 去掉字体字号，跟随当前主题

    def _changed(self):
        self.viewport().update()
        self.edited.emit()

    def loadResource(self, kind, url):
        if kind == QTextDocument.ResourceType.ImageResource.value:
            p = os.path.join(self.store.img_dir, os.path.basename(url.toString()))
            img = QImage(p)
            if not img.isNull():
                return img
        return super().loadResource(kind, url)

    # ---- 插入图片
    def pick_images(self):
        files, _ = QFileDialog.getOpenFileNames(self, self._tr("插入图片"), "",
                                                self._tr("图片") + " (*.png *.jpg *.jpeg *.bmp *.gif *.webp)")
        for f in files:
            self.insert_image(QImage(f))

    def insert_image(self, img):
        name = self.store.save_image(img)
        if not name:
            return False
        w = min(img.width(), max(120, self.viewport().width() - 24), 480)
        fmt = QTextImageFormat()
        fmt.setName(name)
        c = self.textCursor()
        c.insertImage(self._fmt(fmt, w))
        self.setTextCursor(c)
        return True

    def canInsertFromMimeData(self, src):
        return src.hasImage() or src.hasUrls() or super().canInsertFromMimeData(src)

    def insertFromMimeData(self, src):
        if src.hasImage():
            self.insert_image(QImage(src.imageData()))
            return
        if src.hasUrls():
            done = False
            for u in src.urls():
                p = u.toLocalFile()
                if p.lower().endswith(IMG_EXT):
                    done = self.insert_image(QImage(p)) or done
            if done:
                return
        if src.hasText():
            self.insertPlainText(src.text())

    # ---- 找到鼠标下的图片
    def _image_at(self, pos):
        """返回 (位置, 图片格式, 区域)；pos 为视口坐标。"""
        c = self.cursorForPosition(pos)
        for p in (c.position(), c.position() - 1):
            hit = self._image_info(p)
            if hit and hit[2].adjusted(-2, -2, self.EDGE, 2).contains(pos):
                return hit
        return None

    def _image_info(self, p):
        if p is None or p < 0:
            return None
        c = QTextCursor(self.document())
        if p + 1 >= self.document().characterCount():
            return None
        c.setPosition(p)
        c.setPosition(p + 1, QTextCursor.MoveMode.KeepAnchor)
        f = c.charFormat()
        if not f.isImageFormat():
            return None
        f = f.toImageFormat()
        c0 = QTextCursor(self.document())
        c0.setPosition(p)
        c1 = QTextCursor(self.document())
        c1.setPosition(p + 1)
        r0, r1 = self.cursorRect(c0), self.cursorRect(c1)
        w = max(1, r1.left() - r0.left()) if r1.top() == r0.top() else int(f.width() or 0)
        h = round(w * self._ratio(f)) if w > 1 else r0.height()
        return p, f, QRect(r0.left(), r0.bottom() - h + 1, w, h)

    def _set_width(self, p, fmt, w, ratio=None):
        w = int(max(32, min(w, max(60, self.viewport().width() - 12), MAX_IMG_SIDE)))
        nf = self._fmt(fmt, w)
        c = QTextCursor(self.document())
        c.setPosition(p)
        c.setPosition(p + 1, QTextCursor.MoveMode.KeepAnchor)
        c.setCharFormat(nf)

    def _image(self, fmt):
        name = os.path.basename(fmt.name())
        cache = self.__dict__.setdefault("_img_cache", {})
        if name not in cache:
            img = QImage(os.path.join(self.store.img_dir, name))
            cache[name] = (img.width(), img.height()) if not img.isNull() else (320, 240)
        return cache[name]

    def _ratio(self, fmt, rect=None):
        w, h = self._image(fmt)
        return h / max(1, w)

    def _natural_width(self, fmt):
        return self._image(fmt)[0]

    # ---- 鼠标：拖动右边缘调整图片大小
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            hit = self._image_at(e.position().toPoint())
            if hit:
                p, fmt, r = hit
                self._sel = p
                if e.position().x() >= r.right() - self.EDGE:
                    self._resize = (p, r.left(), self._ratio(fmt, r))
                    self.viewport().update()
                    return
            else:
                self._sel = None
            self.viewport().update()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._resize:
            p, left, ratio = self._resize
            info = self._image_info(p)
            if info:
                self._set_width(p, info[1], pos.x() - left, ratio)
            return
        hit = self._image_at(pos)
        if hit and pos.x() >= hit[2].right() - self.EDGE:
            self.viewport().setCursor(Qt.CursorShape.SizeHorCursor)
        elif hit:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._resize:
            self._resize = None
            self.viewport().update()
            return
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            hit = self._image_at(e.position().toPoint())
            if hit:
                p, fmt, r = hit
                step = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
                self._set_width(p, fmt, r.width() * step, self._ratio(fmt, r))
                self._sel = p
                return
        super().wheelEvent(e)

    def keyPressEvent(self, e):
        self._sel = None
        super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        m = self.createStandardContextMenu(e.pos())
        hit = self._image_at(e.pos())
        first = m.actions()[0] if m.actions() else None
        if hit:
            p, fmt, r = hit
            ratio = self._ratio(fmt, r)
            sub = QMenu(self._tr("图片大小"), m)
            for label, w in ((self._tr("小图"), 160), (self._tr("中图"), 320), (self._tr("大图"), 480),
                             (self._tr("原始大小"), self._natural_width(fmt)),
                             (self._tr("适应宽度"), self.viewport().width() - 16)):
                sub.addAction(f"{label}  ·  {int(w)} px" if label != self._tr("适应宽度") else label,
                              lambda w=w: self._set_width(p, fmt, w, ratio))
            m.insertMenu(first, sub)
            m.insertAction(first, m.addAction(self._tr("删除图片"), lambda: self._delete_at(p)))
        m.insertAction(first, m.addAction(self._tr("插入图片…"), self.pick_images))
        m.insertSeparator(first)
        m.exec(e.globalPos())

    def _delete_at(self, p):
        c = QTextCursor(self.document())
        c.setPosition(p)
        c.setPosition(p + 1, QTextCursor.MoveMode.KeepAnchor)
        c.removeSelectedText()
        self._sel = None

    def paintEvent(self, e):
        super().paintEvent(e)
        info = self._image_info(self._sel) if self._sel is not None else None
        if not info:
            return
        r = info[2]
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = self.palette().highlight().color()
        p.setPen(QPen(col, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(r).adjusted(0.5, 0.5, -0.5, -0.5))
        p.setBrush(col)
        p.setPen(QPen(QColor("white"), 1))
        p.drawRoundedRect(QRectF(r.right() - 4, r.center().y() - 9, 8, 18), 3, 3)   # 右边缘手柄


class TitleLabel(QLabel):
    """便签名：按住可拖动小窗，双击直接重命名。"""
    doubleClicked = pyqtSignal()

    def mousePressEvent(self, e):
        e.ignore()                     # 交给小窗处理拖动

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
            e.accept()


class NotePanel(QFrame):
    """便签小窗里的一张便签卡片：标题条（名字 / 菜单 / 折叠 / 移除）+ 编辑区，可单独折叠。"""
    HEAD_H = 34
    MIN_H = 120

    def __init__(self, win, st=None):
        super().__init__(win)
        self.setObjectName("notePanel")
        self.win, self.main, self.store = win, win.main, win.store
        st = dict(st or {})
        self.collapsed = bool(st.get("collapsed"))
        self.h = max(self.MIN_H, int(st.get("h", 220)))
        self.nid = st.get("note")
        self._html = None
        self._dead = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 4, 6, 6)
        lay.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(3)
        head.setContentsMargins(0, 0, 0, 0)
        self.title = TitleLabel(objectName="mfTitle")
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title.setFixedHeight(self.HEAD_H - 6)
        self.title.doubleClicked.connect(self.start_rename)
        head.addWidget(self.title, 1)
        self.title_edit = QLineEdit(objectName="mfRename")
        self.title_edit.hide()
        self.title_edit.editingFinished.connect(self.finish_rename)
        head.addWidget(self.title_edit, 1)
        self.b_menu = QPushButton("", objectName="mfBtn")
        self.b_menu.clicked.connect(self.note_menu)
        self.b_fold = QPushButton(objectName="mfBtn")
        self.b_fold.clicked.connect(lambda: self.set_collapsed(not self.collapsed))
        self.b_close = QPushButton("", objectName="mfClose")
        self.b_close.clicked.connect(lambda: self.win.remove_panel(self))
        for b in (self.b_menu, self.b_fold, self.b_close):
            b.setFixedSize(24, 24)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            head.addWidget(b)
        lay.addLayout(head)
        self.edit = NoteEdit(self.store, self.tr, self)
        self.edit.setObjectName("memoEdit")
        self.edit.edited.connect(self.on_edit)
        lay.addWidget(self.edit, 1)
        self.info = QLabel(objectName="mfInfo")
        lay.addWidget(self.info)
        QShortcut(QKeySequence("F2"), self, activated=self.start_rename,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.store.changed.connect(self.on_store)
        self.retranslate()
        self.load_note(self.nid if self.store.get(self.nid) else None)
        self.apply_collapsed()

    def tr(self, s):
        return self.main.tr(s)

    def retranslate(self):
        self.edit.setPlaceholderText(self.tr("写点什么…可粘贴或拖入图片，内容会自动保存"))
        self.b_menu.setToolTip(self.tr("切换便签、重命名、插入图片"))
        self.b_close.setToolTip(self.tr("从小窗移除（便签内容保留）"))
        self.title.setToolTip(self.tr("双击或按 F2 重命名 · 按住拖动小窗"))
        self.b_fold.setToolTip(self.tr("展开") if self.collapsed else self.tr("折叠"))
        self.update_title()

    def update_title(self):
        n = self.store.get(self.nid)
        self._title_text = note_title(n, self.tr("空白便签")) if n else self.tr("备忘录")
        self._elide()
        self.info.setText(self.tr("已保存 · {t}").format(t=when(n["updated"], self.tr("今天"))) if n else "")

    def _elide(self):
        self.title.setText(self.title.fontMetrics().elidedText(
            getattr(self, "_title_text", ""), Qt.TextElideMode.ElideRight, max(20, self.title.width() - 4)))

    # ---- 便签
    def load_note(self, nid):
        if nid is None:
            shown = {p.nid for p in self.win.panels if p is not self}
            ns = [n for n in self.store.sorted() if n["id"] not in shown] or self.store.sorted()
            nid = ns[0]["id"] if ns else None
        self.nid = nid
        n = self.store.get(nid)
        self.edit.load(n)
        self._html = n.get("html") if n else None
        self.update_title()
        self.win.save_later()

    def new_note(self):
        n = self.store.new(source=self)
        self.load_note(n["id"])
        if self.collapsed:
            self.set_collapsed(False)
        self.edit.setFocus()

    def start_rename(self):
        if self.store.get(self.nid) is None:
            self.nid = self.store.new(source=self)["id"]
        n = self.store.get(self.nid)
        self.title.hide()
        self.title_edit.setPlaceholderText(note_title({"text": n.get("text", "")}, self.tr("空白便签")))
        self.title_edit.setText(n.get("title") or "")
        self.title_edit.show()
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def finish_rename(self, cancel=False):
        if not self.title_edit.isVisible():
            return
        self.title_edit.hide()
        self.title.show()
        if not cancel:
            self.store.set_title(self.nid, self.title_edit.text(), source=self)
        self.update_title()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self.title_edit.isVisible():
            self.finish_rename(cancel=True)
            return
        super().keyPressEvent(e)

    def note_menu(self):
        m = QMenu(self)
        shown = {p.nid for p in self.win.panels if p is not self}
        for n in self.store.sorted()[:30]:
            a = m.addAction(("📌 " if n.get("pinned") else "") + note_title(n, self.tr("空白便签"))
                            + ("   ◧" if n["id"] in shown else ""))
            a.setCheckable(True)
            a.setChecked(n["id"] == self.nid)
            a.triggered.connect(lambda _, nid=n["id"]: self.win.show_in(self, nid))
        if self.store.notes:
            m.addSeparator()
        m.addAction(self.tr("新建便签"), self.new_note)
        m.addAction(self.tr("重命名") + "\tF2", self.start_rename)
        m.addAction(self.tr("插入图片…"), self.insert_images)
        m.addSeparator()
        k = len(self.win.panels)
        a = m.addAction(self.tr("在下方再加一张（{n}/{m}）").format(n=k, m=MAX_FLOATS), self.win.add_more)
        a.setEnabled(k < MAX_FLOATS)
        m.addAction(self.tr("在主窗口中管理"), self.main.show_memo_page)
        m.exec(self.b_menu.mapToGlobal(QPoint(0, self.b_menu.height())))

    def insert_images(self):
        if self.store.get(self.nid) is None:
            self.nid = self.store.new(source=self)["id"]
        if self.collapsed:
            self.set_collapsed(False)
        self.edit.setFocus()
        self.edit.pick_images()

    def on_edit(self):
        html, text = self.edit.content()
        if self.store.get(self.nid) is None:
            if not text.strip() and html is None:
                return
            self.nid = self.store.new(source=self)["id"]
            self.win.save_later()
        self._html = html
        self.store.set_content(self.nid, html, text, source=self)
        self.update_title()

    def on_store(self, nid, source):
        if source is self or self._dead:
            return
        if self.store.get(self.nid) is None:
            self.load_note(None)
        elif nid == self.nid:
            n = self.store.get(nid)
            if n.get("html") != self._html or (n.get("html") is None
                                               and n.get("text", "") != self.edit.toPlainText()):
                cur = self.edit.textCursor().position()
                self.edit.load(n)
                self._html = n.get("html")
                c = self.edit.textCursor()
                c.setPosition(min(cur, self.edit.document().characterCount() - 1))
                self.edit.setTextCursor(c)
        self.update_title()

    # ---- 折叠
    def set_collapsed(self, on):
        if on == self.collapsed:
            return
        if on:
            self.finish_rename()
            self.h = max(self.MIN_H, self.height())
        self.collapsed = on
        self.win._fitting = True          # 结构变化期间不记录被挤压 / 拉伸的临时高度
        self.apply_collapsed()
        self.win.relayout()

    def apply_collapsed(self):
        on = self.collapsed
        self.edit.setVisible(not on)
        self.info.setVisible(not on)
        self.b_fold.setText("" if on else "")
        self.b_fold.setToolTip(self.tr("展开") if on else self.tr("折叠"))
        if on:
            self.setFixedHeight(self.HEAD_H + 4)
        else:
            self.setMinimumHeight(self.MIN_H)
            self.setMaximumHeight(16777215)

    def state(self):
        return {"note": self.nid, "collapsed": self.collapsed,
                "h": self.h if self.collapsed else max(self.MIN_H, self.height())}

    # ---- 事件
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self.collapsed and not self.win._fitting and self.isVisible():
            self.h = max(self.MIN_H, self.height())
        self._elide()

    def mouseDoubleClickEvent(self, e):
        if e.position().y() <= self.HEAD_H:    # 双击标题条空白处：折叠 / 展开
            self.set_collapsed(not self.collapsed)
        else:
            e.ignore()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.main.theme_colors()["faint"]))   # 左侧拖动点
        for i in range(3):
            for j in range(2):
                p.drawEllipse(QRectF(5 + j * 3.5, (self.HEAD_H + 4) / 2 - 5 + i * 4.5, 2, 2))


class MemoFloat(QWidget):
    """桌面便签小窗：置顶；最多 3 张便签自上而下排列，每张可单独折叠；
    按住标题、边框等空白处拖动，右下角调整大小；位置和显示的便签会被记住。"""
    SPACING = 8

    def __init__(self, main, store):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.main, self.store = main, store
        self.setObjectName("memoFloat")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(230)
        self.panels = []
        self._drag = None
        self._fitting = False
        st = dict(main.cfg.get("memo_float") or {})
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 6)
        lay.setSpacing(self.SPACING)
        self.col = QVBoxLayout()
        self.col.setSpacing(self.SPACING)
        self.col.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.col, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        self.b_add = QPushButton(objectName="mfAdd")
        self.b_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.b_add.clicked.connect(self.add_more)
        foot.addWidget(self.b_add)
        foot.addStretch(1)
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(14, 14)
        foot.addWidget(self.grip, 0, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        lay.addLayout(foot)
        self._save_timer = QTimer(self, singleShot=True, interval=600, timeout=self.save_state)

        scr = QGuiApplication.primaryScreen().availableGeometry()
        w = int(st.get("w", 270))
        x, y = st.get("x"), st.get("y")
        if x is None or y is None:
            x, y = scr.right() - w - 24, scr.top() + 100
        r = QRect(int(x), int(y), w, 300)
        if not any(s.availableGeometry().intersects(r) for s in QGuiApplication.screens()):
            r.moveTo(scr.right() - w - 24, scr.top() + 100)   # 显示器拔掉后不至于找不回小窗
        self.setGeometry(r)
        panels = st.get("panels")
        if not isinstance(panels, list) or not panels:      # 旧版只有一个便签
            panels = [{"note": st.get("note"), "collapsed": st.get("collapsed"), "h": 200}]
        for ps in panels[:MAX_FLOATS]:
            self._add(ps)
        self.retranslate()
        self.relayout()

    def tr(self, s):
        return self.main.tr(s)

    def retranslate(self):
        for p in self.panels:
            p.retranslate()
        self.update_add()

    def update_add(self):
        k = len(self.panels)
        self.b_add.setText("＋ " + self.tr("添加便签（{n}/{m}）").format(n=k, m=MAX_FLOATS))
        self.b_add.setVisible(k < MAX_FLOATS)

    # ---- 卡片增删
    def _add(self, st):
        p = NotePanel(self, st)
        self.panels.append(p)
        self.col.addWidget(p)
        return p

    def add_panel(self, nid=None):
        if len(self.panels) >= MAX_FLOATS:
            return None
        self._fitting = True              # 新卡片加入时其他卡片会被暂时挤压，不记录这个高度
        p = self._add({"note": nid, "h": 200})
        p.show()
        self.update_add()
        self.relayout()
        self.save_later()
        return p

    def add_more(self):
        """在下方再加一张：显示一条还没显示的便签，都显示了就新建一条。"""
        shown = {p.nid for p in self.panels}
        nid = next((n["id"] for n in self.store.sorted() if n["id"] not in shown), None)
        if nid is None:
            nid = self.store.new()["id"]
        p = self.add_panel(nid)
        if p:
            p.edit.setFocus()

    def remove_panel(self, p):
        if len(self.panels) <= 1:
            self.main.set_memo_float(False)
            return
        p.finish_rename()
        self._fitting = True
        p._dead = True
        self.panels.remove(p)
        self.col.removeWidget(p)
        p.hide()
        p.deleteLater()
        self.update_add()
        self.relayout()
        self.save_later()

    def show_in(self, panel, nid):
        """在某张卡片里显示 nid；若别的卡片已显示它，两张互换。"""
        other = next((p for p in self.panels if p is not panel and p.nid == nid), None)
        if other:
            other.load_note(panel.nid)
        panel.load_note(nid)

    def open_note(self, nid):
        """主窗口「在小窗中打开」：已显示就展开它；不足 3 张就在下方加一张；满了替换最后一张。"""
        p = next((p for p in self.panels if p.nid == nid), None)
        if p is None:
            p = self.add_panel(nid)
        if p is None:
            p = self.panels[-1]
            p.load_note(nid)
        if p.collapsed:
            p.set_collapsed(False)
        return p

    def new_note(self):
        """托盘「新建便签」：有空位就在下方加一张新便签，否则在最后一张里新建。"""
        p = self.add_panel(self.store.new()["id"]) if len(self.panels) < MAX_FLOATS else None
        if p is None:
            p = self.panels[-1]
            p.new_note()
        if p.collapsed:
            p.set_collapsed(False)
        p.edit.setFocus()
        return p

    # ---- 排列：窗口高度 = 各卡片高度之和，向下延伸
    def relayout(self):
        self._fitting = True
        m = self.layout().contentsMargins()
        foot = max(self.grip.height(), self.b_add.sizeHint().height() if len(self.panels) < MAX_FLOATS else 0)
        fixed = m.top() + m.bottom() + foot + self.SPACING * len(self.panels)
        total = minimum = fixed
        for p in self.panels:
            self.col.setStretchFactor(p, 0 if p.collapsed else max(1, p.h))
            total += (NotePanel.HEAD_H + 4) if p.collapsed else p.h
            minimum += (NotePanel.HEAD_H + 4) if p.collapsed else NotePanel.MIN_H
        scr = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        total = min(total, scr.height() - 16)
        g = self.geometry()
        y = g.y() if g.y() + total <= scr.bottom() else max(scr.top() + 8, scr.bottom() - total)
        if all(p.collapsed for p in self.panels):
            self.setFixedHeight(total)
        else:
            self.setMinimumHeight(min(minimum, total))
            self.setMaximumHeight(16777215)
        self.setGeometry(g.x(), y, g.width(), total)
        self.layout().activate()
        self._fitting = False
        self.save_later()

    # ---- 状态
    def save_later(self):
        self._save_timer.start()

    def state(self):
        g = self.geometry()
        return {"x": g.x(), "y": g.y(), "w": g.width(), "panels": [p.state() for p in self.panels]}

    def save_state(self):
        self.main.cfg["memo_float"] = self.state()
        self.main.cfg.pop("memo_floats", None)
        self.main.save()

    def moveEvent(self, e):
        super().moveEvent(e)
        self.save_later()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.save_later()

    # ---- 拖动：编辑区和按钮以外的任意位置都能按住拖动
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            for p in self.panels:
                p.finish_rename()
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.unsetCursor()

    # ---- 外观
    def apply_theme(self):
        self.update()
        for p in self.panels:
            p.update()

    def paintEvent(self, e):
        t = self.main.theme_colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(edge_color(t), 2))                 # 深色主题色描边
        p.setBrush(QColor(t["frame"]))                   # 窗口底色比便签卡片深
        p.drawRoundedRect(r, 12, 12)

    def closeEvent(self, e):
        for p in self.panels:
            p.finish_rename()
        self.save_state()
        self.store.flush()
        super().closeEvent(e)
