"""格式转换核心：把任意文件读成统一的 Content（页面图像 / 文字 / 图片），再写出目标格式。"""
from __future__ import annotations

import base64
import io
import os
import re
import shutil
import struct
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageSequence

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pillow_heif = None

IMAGE_FORMATS = ["PNG", "SVG", "ICO", "JPEG", "WEBP", "BMP", "GIF", "DDS", "CUR",
                 "TIFF", "HEIC", "PSD", "AVIF", "HDR", "TGA",
                 "RGB", "JFIF", "HEIF", "JP2", "WBMP", "JBG", "JPE", "PCX", "EXR",
                 "PPM", "MAP", "PGM", "JIF", "PDB", "RAS"]
DOC_FORMATS = ["PDF", "DOC", "DOCX", "DOCM", "ODT", "XPS", "RTF", "DOT", "DOTX",
               "DJVU", "DOTM", "ABW", "KWD", "AW", "DBK", "OXPS", "SXW"]
SHEET_FORMATS = ["XLSX", "XLSM", "CSV"]
VECTOR_FORMATS = ["SVG", "AI", "PLT", "EPS", "WMF", "SK", "EMF", "FIG", "CGM", "SK1", "PS"]

FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"
PAGE_W, PAGE_H, MARGIN = 1240, 1754, 100  # A4 @150dpi


@dataclass
class Content:
    title: str
    pages: list = field(default_factory=list)     # 用于输出图像格式的整页图像
    text: list = field(default_factory=list)      # 段落文字
    pictures: list = field(default_factory=list)  # 嵌入文档的图片
    blocks: list = field(default_factory=list)    # 按顺序的 ("p", 文本) / ("table", 行列表)，保留表格结构

    def doc_blocks(self):
        return self.blocks or [("p", t) for t in self.text]

    def page_images(self):
        if self.pages:
            return self.pages
        if self.pictures:
            return self.pictures
        if any(k == "table" for k, _ in self.blocks):
            import pymupdf
            tmp = os.path.join(tempfile.mkdtemp(), "t.pdf")
            write_pdf(self, tmp)
            out = []
            for i, pg in enumerate(pymupdf.open(tmp)):
                if i >= 200:
                    break
                pix = pg.get_pixmap(dpi=150)
                out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
            return out
        return render_text_pages(self.text or [self.title])

    def doc_pictures(self):
        if self.pictures:
            return self.pictures
        return [] if self.text else self.pages


# ---------------------------------------------------------------- 读取

def _rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGB", "RGBA"):
        return img.copy()
    if img.mode in ("I;16", "I", "F"):
        a = np.asarray(img, dtype=np.float64)
        a = (a - a.min()) / max(a.max() - a.min(), 1e-9) * 255
        return Image.fromarray(a.astype(np.uint8)).convert("RGB")
    return img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")


def _pdf_page_blocks(page):
    """识别 PDF 页面中的表格；表格以外的文字按位置顺序作为段落。"""
    try:
        tables = page.find_tables().tables
    except Exception:
        tables = []
    items, boxes = [], [tuple(t.bbox) for t in tables]
    for t, box in zip(tables, boxes):
        rows = [[None if x is None else x.strip() for x in r] for r in t.extract()]
        rows = [r for r in rows if any(x for x in r)]
        if rows:
            items.append((box[1], ("table", rows)))
    for x0, y0, x1, y1, txt, *_ in page.get_text("blocks"):
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in boxes):
            continue
        for ln in txt.splitlines():
            if ln.strip():
                items.append((y0, ("p", ln.strip())))
    items.sort(key=lambda it: it[0])
    return [b for _, b in items]


def _cell_str(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d %H:%M" if getattr(v, "hour", 0) or getattr(v, "minute", 0) else "%Y-%m-%d")
    return str(v)


def _sheet_rows(ws):
    """工作表 → 行列表；横向合并单元格的后续格记为 None，去掉末尾空行空列。"""
    merged = {}
    for mr in ws.merged_cells.ranges:
        for r in range(mr.min_row, mr.max_row + 1):
            for col in range(mr.min_col, mr.max_col + 1):
                if (r, col) != (mr.min_row, mr.min_col):
                    merged[(r, col)] = r == mr.min_row  # 同一行内的合并 → None
    rows = []
    for r, row in enumerate(ws.iter_rows(values_only=True), 1):
        out = []
        for col, v in enumerate(row, 1):
            m = merged.get((r, col))
            out.append(None if m else ("" if m is False else _cell_str(v)))
        rows.append(out)
    while rows and not any(x for x in rows[-1]):
        rows.pop()
    ncol = max((max((i + 1 for i, x in enumerate(r) if x), default=0) for r in rows), default=0)
    rows = [r[:ncol] for r in rows]
    return rows if ncol else []


def _merge_spans(row, ncol):
    """把一行展开为 [(起始列, 结束列, 文本)]；None 表示与左侧单元格合并。"""
    row = list(row) + [""] * (ncol - len(row))
    out, j = [], 0
    while j < ncol:
        k = j + 1
        while k < ncol and row[k] is None:
            k += 1
        out.append((j, k - 1, row[j] or ""))
        j = k
    return out


def _decode_text(data: bytes):
    if b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return None
    for enc in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            s = data.decode(enc)
        except UnicodeDecodeError:
            continue
        bad = sum(1 for c in s[:4000] if ord(c) < 32 and c not in "\r\n\t\f")
        if bad < 5:
            return s
    return None


def _strip_rtf(s: str) -> str:
    s = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), s)
    s = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("latin-1"), s)
    s = re.sub(r"\\par[d]?\b", "\n", s)
    s = re.sub(r"\{\\\*[^{}]*\}", "", s)
    s = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", s)
    return s.replace("{", "").replace("}", "")


def load(path: str) -> Content:
    name = os.path.splitext(os.path.basename(path))[0]
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    c = Content(title=name)

    # 1) 版式文档 / 电子书 / SVG：PyMuPDF
    with open(path, "rb") as f:
        magic = f.read(5)
    if ext in ("pdf", "xps", "oxps", "epub", "mobi", "fb2", "cbz", "svg") or (ext == "ai" and magic == b"%PDF-"):
        import pymupdf
        with open(path, "rb") as f:
            doc = pymupdf.open(stream=f.read(), filetype="pdf" if ext == "ai" else ext)
        for i, page in enumerate(doc):
            if i >= 200:
                break
            pix = page.get_pixmap(dpi=150 if ext != "svg" else 96, alpha=(ext == "svg"))
            mode = "RGBA" if pix.alpha else "RGB"
            c.pages.append(Image.frombytes(mode, (pix.width, pix.height), pix.samples))
            c.text += [p for p in page.get_text().split("\n") if p.strip()]
            if ext != "svg":
                c.blocks += _pdf_page_blocks(page)
        if ext == "svg":
            c.pictures, c.text = c.pages, []
        return c

    # 2) 表格：Excel / CSV
    if ext in ("xlsx", "xlsm", "xltx", "xltm"):
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)  # 公式取计算后的值
        for ws in wb.worksheets:
            rows = _sheet_rows(ws)
            if not rows:
                continue
            if len(wb.worksheets) > 1:
                c.blocks.append(("p", ws.title))
            c.blocks.append(("table", rows))
            c.text += ["\t".join(x or "" for x in r) for r in rows]
        return c
    if ext in ("csv", "tsv"):
        import csv
        with open(path, "rb") as f:
            txt = _decode_text(f.read()) or ""
        rows = list(csv.reader(io.StringIO(txt), delimiter="\t" if ext == "tsv" else ","))
        c.blocks = [("table", rows)] if rows else []
        c.text = ["\t".join(r) for r in rows]
        return c

    # 2b) Word 系列
    if ext in ("docx", "docm", "dotx", "dotm"):
        import docx
        buf = io.BytesIO()  # python-docx 只认 .docx 内容类型，宏/模板版需改写后读取
        with zipfile.ZipFile(path) as zi, zipfile.ZipFile(buf, "w") as zo:
            for it in zi.infolist():
                data = zi.read(it)
                if it.filename == "[Content_Types].xml":
                    for ct in DOCX_CT.values():
                        data = data.replace(ct.encode(), DOCX_CT["DOCX"].encode())
                zo.writestr(it, data)
        d = docx.Document(buf)
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        for el in d.element.body.iterchildren():  # 按文档顺序读取段落与表格
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "p":
                t = Paragraph(el, d).text
                if t.strip():
                    c.blocks.append(("p", t))
                    c.text.append(t)
            elif tag == "tbl":
                rows = [[cell.text for cell in row.cells] for row in Table(el, d).rows]
                c.blocks.append(("table", rows))
                c.text += [" | ".join(r) for r in rows]
        for rel in d.part.rels.values():
            if "image" in rel.reltype:
                try:
                    c.pictures.append(_rgb(Image.open(io.BytesIO(rel.target_part.blob))))
                except Exception:
                    pass
        return c

    if ext in ("odt", "ott", "odp", "ods"):
        from odf import opendocument, teletype, text as odftext
        d = opendocument.load(path)
        c.text = [teletype.extractText(p) for p in d.getElementsByType(odftext.P)]
        c.text = [t for t in c.text if t.strip()]
        for fn, data in getattr(d, "Pictures", {}).items():
            try:
                c.pictures.append(_rgb(Image.open(io.BytesIO(data[1]))))
            except Exception:
                pass
        return c

    if ext == "kwd" and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            xml = z.read("maindoc.xml").decode("utf-8", "ignore")
        import html
        c.text = [html.unescape(t) for t in re.findall(r"<TEXT[^>]*>(.*?)</TEXT>", xml, re.S)]
        return c

    # 3) 图像（含 HEIC/AVIF/PSD/DDS 等 Pillow 能读的）
    try:
        if ext == "cur":  # 按 ICO 读取（PNG 内嵌的光标 Pillow 的 CUR 插件读不了）
            data = bytearray(open(path, "rb").read())
            data[2:4] = b"\x01\x00"
            img = Image.open(io.BytesIO(bytes(data)))
        else:
            img = Image.open(path)
        frames = [_rgb(f) for i, f in zip(range(100), ImageSequence.Iterator(img))]
        c.pages = c.pictures = frames
        return c
    except Exception:
        pass

    # 4) 音视频：取一帧
    try:
        import av
        with av.open(path) as cont:
            if cont.streams.video:
                st = cont.streams.video[0]
                if st.duration and st.time_base:
                    cont.seek(int(st.duration * 0.1), stream=st)
                for frame in cont.decode(st):
                    c.pages = c.pictures = [frame.to_image()]
                    break
                return c
            if cont.streams.audio:
                dur = (cont.duration or 0) / 1e6
                c.text = [f"音频文件：{os.path.basename(path)}", f"时长：{dur:.1f} 秒",
                          f"编码：{cont.streams.audio[0].codec_context.name}"]
                c.text += [f"{k}: {v}" for k, v in cont.metadata.items()]
                return c
    except Exception:
        pass

    # 5) 文本类 / 其它二进制
    with open(path, "rb") as f:
        data = f.read(8 * 1024 * 1024)
    s = _decode_text(data)
    if s is not None:
        if ext == "rtf" or s.startswith("{\\rtf"):
            s = re.sub(r"\{\\fonttbl.*?\}\}", "", s, flags=re.S)
            s = re.sub(r"\{\\pict.*?\}", "", s, flags=re.S)
            s = _strip_rtf(s)
        elif ext in ("html", "htm", "xml", "xhtml", "dbk", "abw", "aw", "fodt"):
            s = re.sub(r"<(script|style|data)[^>]*>.*?</\1>", "", s, flags=re.S | re.I)
            s = re.sub(r"<br\s*/?>|</p>|</div>|</h\d>|</para>", "\n", s, flags=re.I)
            s = re.sub(r"<[^>]+>", "", s)
            import html
            s = html.unescape(s)
        c.text = [ln.rstrip() for ln in s.splitlines()]
        while c.text and not c.text[-1]:
            c.text.pop()
        return c

    # 无法解析的二进制：生成文件信息 + 十六进制预览
    size = os.path.getsize(path)
    c.text = [f"文件：{os.path.basename(path)}", f"大小：{size:,} 字节", "十六进制预览（前 2 KB）：", ""]
    for off in range(0, min(len(data), 2048), 16):
        chunk = data[off:off + 16]
        hx = " ".join(f"{b:02X}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        c.text.append(f"{off:08X}  {hx:<47}  {asc}")
    return c


# ---------------------------------------------------------------- 文字渲染为页面图像

def render_text_pages(paras, size=28):
    font = ImageFont.truetype(FONT_PATH, size)
    lh = int(size * 1.6)
    maxw = PAGE_W - 2 * MARGIN
    lines = []
    for p in paras:
        if not p:
            lines.append("")
            continue
        cur = ""
        for ch in p.replace("\t", "    "):
            if font.getlength(cur + ch) > maxw:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    per = (PAGE_H - 2 * MARGIN) // lh
    pages = []
    for i in range(0, max(len(lines), 1), per):
        im = Image.new("RGB", (PAGE_W, PAGE_H), "white")
        d = ImageDraw.Draw(im)
        for j, ln in enumerate(lines[i:i + per]):
            d.text((MARGIN, MARGIN + j * lh), ln, fill="black", font=font)
        pages.append(im)
        if len(pages) >= 200:
            break
    return pages


# ---------------------------------------------------------------- 图像写出

def _png_bytes(img):
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def _ico_bytes(img, cur=False):
    img = img.convert("RGBA")
    img.thumbnail((256, 256))
    sizes = [s for s in [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
             if s[0] <= max(img.size)] or [img.size]
    sq = Image.new("RGBA", (max(img.size),) * 2, (0, 0, 0, 0))
    sq.paste(img, ((sq.width - img.width) // 2, (sq.height - img.height) // 2))
    b = io.BytesIO()
    sq.save(b, "ICO", sizes=sizes)
    data = bytearray(b.getvalue())
    if cur:
        data[2:4] = struct.pack("<H", 2)
        n = struct.unpack("<H", data[4:6])[0]
        for i in range(n):
            off = 6 + i * 16
            data[off + 4:off + 8] = struct.pack("<HH", 0, 0)  # 热点 (0,0)
    return bytes(data)


def _psd_bytes(img):
    img = img.convert("RGBA" if img.mode == "RGBA" else "RGB")
    ch = len(img.getbands())
    w, h = img.size
    out = io.BytesIO()
    out.write(b"8BPS" + struct.pack(">H6xHIIHH", 1, ch, h, w, 8, 3))
    out.write(struct.pack(">III", 0, 0, 0))  # 色彩模式 / 资源 / 图层
    out.write(struct.pack(">H", 0))  # 无压缩
    a = np.asarray(img)
    for i in range(ch):
        out.write(a[:, :, i].tobytes())
    return out.getvalue()


def _hdr_bytes(img):
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    rgb = rgb ** 2.2  # 转线性
    h, w, _ = rgb.shape
    mx = rgb.max(axis=2)
    mant, exp = np.frexp(mx)
    scale = np.where(mx > 1e-32, mant * 256.0 / np.maximum(mx, 1e-32), 0)
    rgbe = np.zeros((h, w, 4), np.uint8)
    rgbe[..., :3] = np.clip(rgb * scale[..., None], 0, 255).astype(np.uint8)
    rgbe[..., 3] = np.where(mx > 1e-32, exp + 128, 0).astype(np.uint8)
    head = f"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y {h} +X {w}\n".encode()
    return head + rgbe.tobytes()


def _svg_bytes(img):
    b64 = base64.b64encode(_png_bytes(img)).decode()
    w, h = img.size
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<image width="{w}" height="{h}" xlink:href="data:image/png;base64,{b64}"/></svg>').encode()


def _flat(img, mode="RGB"):
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    return img.convert(mode)


def _wbmp_bytes(img):
    def mb(n):
        out = [n & 0x7F]
        n >>= 7
        while n:
            out.append(0x80 | (n & 0x7F))
            n >>= 7
        return bytes(reversed(out))
    bw = _flat(img, "L").convert("1")  # 抖动成黑白，WBMP 中 1=白
    w, h = bw.size
    return b"\x00\x00" + mb(w) + mb(h) + bw.tobytes()


def _ras_bytes(img):
    a = np.asarray(_flat(img))[:, :, ::-1]  # Sun Raster 存 BGR，每行补齐到 2 字节
    h, w, _ = a.shape
    pad = b"\x00" * ((w * 3) % 2)
    data = b"".join(a[y].tobytes() + pad for y in range(h))
    return struct.pack(">8I", 0x59A66A95, w, h, 24, len(data), 1, 0, 0) + data


def _map_bytes(img):
    p = _flat(img).quantize(256)  # ImageMagick MAP：256 色调色板 + 每像素一个索引
    pal = (p.getpalette() + [0] * 768)[:768]
    return bytes(pal) + p.tobytes()


def _pdb_bytes(img, name):
    """Palm ImageViewer 数据库（类型 vIMG / 创建者 View），2 位灰度无压缩。"""
    g = _flat(img, "L")
    g.thumbnail((160, 640))
    w = (g.width + 3) // 4 * 4
    a = np.full((g.height, w), 255, np.uint8)
    a[:, :g.width] = np.asarray(g)
    q = (3 - (a.astype(np.uint16) * 4 // 256)).astype(np.uint8)  # 0=白 3=黑
    packed = (q[:, 0::4] << 6) | (q[:, 1::4] << 4) | (q[:, 2::4] << 2) | q[:, 3::4]
    nm = name.encode("ascii", "replace")[:31].ljust(32, b"\x00")
    rec = nm + bytes([0, 0]) + b"\x00" * 12 + struct.pack(">hhHH", -1, -1, w, g.height) + packed.tobytes()
    hdr = nm + struct.pack(">HHIIIIII4s4sIIH", 0, 0, 0x7C000000, 0x7C000000, 0, 0, 0, 0, b"vIMG", b"View", 0, 0, 1)
    off = len(hdr) + 8 + 2
    hdr += struct.pack(">IBBBB", off, 0x40, 0x6F, 0x80, 0) + b"\x00\x00"
    return hdr + rec


def _exr_bytes(img):
    """OpenEXR 2.0，无压缩扫描线，half 浮点线性 RGB。"""
    rgb = (np.asarray(_flat(img), dtype=np.float32) / 255.0) ** 2.2
    h, w, _ = rgb.shape

    def attr(n, t, v):
        return n.encode() + b"\0" + t.encode() + b"\0" + struct.pack("<i", len(v)) + v
    chl = b"".join(ch + b"\0" + struct.pack("<iBxxxii", 1, 0, 1, 1) for ch in (b"B", b"G", b"R")) + b"\0"
    box = struct.pack("<iiii", 0, 0, w - 1, h - 1)
    head = (struct.pack("<ii", 20000630, 2) + attr("channels", "chlist", chl)
            + attr("compression", "compression", b"\0") + attr("dataWindow", "box2i", box)
            + attr("displayWindow", "box2i", box) + attr("lineOrder", "lineOrder", b"\0")
            + attr("pixelAspectRatio", "float", struct.pack("<f", 1))
            + attr("screenWindowCenter", "v2f", struct.pack("<ff", 0, 0))
            + attr("screenWindowWidth", "float", struct.pack("<f", 1)) + b"\0")
    half = rgb.astype("<f2")
    chunks, offs, pos = [], [], len(head) + 8 * h
    for y in range(h):
        data = half[y, :, 2].tobytes() + half[y, :, 1].tobytes() + half[y, :, 0].tobytes()
        chunk = struct.pack("<ii", y, len(data)) + data
        offs.append(pos)
        chunks.append(chunk)
        pos += len(chunk)
    return head + struct.pack(f"<{h}Q", *offs) + b"".join(chunks)


def _jbg_save(img, path):
    tool = shutil.which("pbmtojbg") or shutil.which("pbmtojbg85")
    if not tool:
        raise RuntimeError("JBG（JBIG）需要 JBIG-KIT 的 pbmtojbg.exe，请把它放到 PATH 中")
    tmp = os.path.join(tempfile.mkdtemp(), "t.pbm")
    _flat(img, "L").convert("1").save(tmp)
    subprocess.run([tool, tmp, path], check=True, creationflags=0x08000000)


def ext_of(fmt):
    return "." + ("jpg" if fmt == "JPEG" else fmt.lower())


def save_image(img, path, fmt):
    fmt = {"JFIF": "JPEG", "JPE": "JPEG", "JIF": "JPEG", "HEIF": "HEIC"}.get(fmt, fmt)
    simple = {"WBMP": _wbmp_bytes, "RAS": _ras_bytes, "MAP": _map_bytes, "EXR": _exr_bytes}
    if fmt == "JBG":
        return _jbg_save(img, path)
    if fmt in ("RGB", "JP2", "PCX", "PPM", "PGM"):
        _flat(img, "L" if fmt == "PGM" else "RGB").save(
            path, {"RGB": "SGI", "JP2": "JPEG2000", "PCX": "PCX", "PPM": "PPM", "PGM": "PPM"}[fmt])
        return
    if fmt in simple:
        data = simple[fmt](img)
    elif fmt == "PDB":
        data = _pdb_bytes(img, os.path.splitext(os.path.basename(path))[0])
    elif fmt == "SVG":
        data = _svg_bytes(img)
    elif fmt in ("ICO", "CUR"):
        data = _ico_bytes(img, cur=fmt == "CUR")
    elif fmt == "PSD":
        data = _psd_bytes(img)
    elif fmt == "HDR":
        data = _hdr_bytes(img)
    else:
        if fmt in ("JPEG", "HEIC") and img.mode != "RGB":
            bg = Image.new("RGB", img.size, "white")
            bg.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = bg
        if fmt == "HEIC":
            if pillow_heif is None:
                raise RuntimeError("HEIC 需要安装 pillow-heif")
            img.save(path, "HEIF", quality=90)
        elif fmt == "DDS":
            img.convert("RGBA").save(path, "DDS")
        else:
            img.save(path, fmt, **({"quality": 92} if fmt in ("JPEG", "WEBP", "AVIF") else {}))
        return
    with open(path, "wb") as f:
        f.write(data)


def write_images(content, out_base, fmt):
    pages = content.page_images()
    ext = ext_of(fmt)
    if fmt in ("GIF", "TIFF") and len(pages) > 1:  # 多帧/多页格式
        path = out_base + ext
        first, rest = pages[0], pages[1:]
        if fmt == "GIF":
            first.convert("RGB").save(path, save_all=True, append_images=[p.convert("RGB") for p in rest],
                                      duration=500, loop=0)
        else:
            first.save(path, save_all=True, append_images=rest, compression="tiff_deflate")
        return [path]
    if len(pages) == 1:
        save_image(pages[0], out_base + ext, fmt)
        return [out_base + ext]
    outs = []
    for i, p in enumerate(pages, 1):
        path = f"{out_base}_{i:03d}{ext}"
        save_image(p, path, fmt)
        outs.append(path)
    return outs


# ---------------------------------------------------------------- 文档写出

def _limit(img, maxw=1600):
    if img.width > maxw:
        img = img.resize((maxw, int(img.height * maxw / img.width)))
    return img


def _wrap(font, text, fs, width):
    lines = []
    for para in (text or "").split("\n"):
        cur = ""
        for ch in para:
            if cur and font.text_length(cur + ch, fs) > width:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines


def write_pdf(c, path):
    import pymupdf
    doc = pymupdf.open()
    font = pymupdf.Font("china-s")
    blocks = c.doc_blocks()
    widest = max((max(len(r) for r in v) for k, v in blocks if k == "table" and v), default=0)
    W, H = (842, 595) if widest > 6 else (595, 842)  # 列多时用横向页面
    M = 40
    st = {"page": None, "y": H}

    def new_page():
        st["page"] = doc.new_page(width=W, height=H)
        st["page"].insert_font(fontname="cs", fontbuffer=font.buffer)
        st["y"] = M

    def need(h):
        if st["page"] is None or st["y"] + h > H - M:
            new_page()

    for kind, v in blocks:
        if kind == "p":
            fs, lh = 11, 17
            for ln in _wrap(font, v, fs, W - 2 * M):
                need(lh)
                if ln:
                    st["page"].insert_text((M, st["y"] + fs), ln, fontname="cs", fontsize=fs)
                st["y"] += lh
            continue
        if not v:
            continue
        ncol = max(len(r) for r in v)
        fs = 9 if ncol <= 8 else 7.5 if ncol <= 14 else 6
        lh, pad = fs * 1.35, 3
        # 列宽：按每列最长内容分配，限制单列不超过总宽的 40%
        need_w = [0.0] * ncol
        for r in v:
            for j, k, val in _merge_spans(r, ncol):
                if j == k:
                    longest = max((font.text_length(x, fs) for x in val.split("\n")), default=0)
                    need_w[j] = max(need_w[j], longest + 2 * pad)
        total = W - 2 * M
        need_w = [min(max(x, 24), total * 0.4) for x in need_w]
        scale = total / sum(need_w)
        cw = [x * scale for x in need_w]
        xs = [M]
        for x in cw:
            xs.append(xs[-1] + x)
        for r in v:
            spans = _merge_spans(r, ncol)
            cells = [(xs[j], xs[k + 1], _wrap(font, val, fs, xs[k + 1] - xs[j] - 2 * pad)) for j, k, val in spans]
            rh = max(len(ls) for _, _, ls in cells) * lh + 2 * pad
            need(rh)
            pg, y = st["page"], st["y"]
            for x0, x1, ls in cells:
                pg.draw_rect(pymupdf.Rect(x0, y, x1, y + rh), color=(0, 0, 0), width=0.5)
                for i, ln in enumerate(ls):
                    if ln:
                        pg.insert_text((x0 + pad, y + pad + fs + i * lh), ln, fontname="cs", fontsize=fs)
            st["y"] += rh
        st["y"] += 10
    for img in c.doc_pictures():
        page = doc.new_page(width=W, height=H)
        r = pymupdf.Rect(M, M, W - M, H - M)
        page.insert_image(r, stream=_png_bytes(_limit(img)), keep_proportion=True)
    if doc.page_count == 0:
        doc.new_page()
    data = doc.tobytes(deflate=True)  # MuPDF 打不开含中文的路径，改由 Python 写文件
    with open(path, "wb") as f:
        f.write(data)


DOCX_CT = {
    "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "DOTX": "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
    "DOCM": "application/vnd.ms-word.document.macroEnabled.main+xml",
    "DOTM": "application/vnd.ms-word.template.macroEnabledTemplate.main+xml",
}


def write_docx(c, path, fmt="DOCX"):
    import docx
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt
    d = docx.Document()
    st = d.styles["Normal"]
    st.font.name = "微软雅黑"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    for kind, v in c.doc_blocks():
        if kind == "p":
            d.add_paragraph(v)
            continue
        ncol = max(len(r) for r in v)
        tb = d.add_table(rows=len(v), cols=ncol)
        tb.style = "Table Grid"
        for i, row in enumerate(v):
            for j, k, val in _merge_spans(row, ncol):
                cell = tb.cell(i, j)
                if k > j:
                    cell = cell.merge(tb.cell(i, k))
                cell.text = val
        d.add_paragraph()
    for img in c.doc_pictures():
        img = _limit(img)
        w_in = min(6.0, img.width / 96)
        d.add_picture(io.BytesIO(_png_bytes(img)), width=Inches(w_in))
    d.part._content_type = DOCX_CT[fmt]
    d.save(path)


def _rtf_escape(s):
    out = []
    for ch in s:
        o = ord(ch)
        if ch in "\\{}":
            out.append("\\" + ch)
        elif o < 128:
            out.append(ch)
        else:
            b = ch.encode("utf-16-le")
            for i in range(0, len(b), 2):
                out.append(f"\\u{struct.unpack('<h', b[i:i + 2])[0]}?")
    return "".join(out)


def write_rtf(c, path):
    parts = [r"{\rtf1\ansi\ansicpg936\deff0{\fonttbl{\f0\fnil\fcharset134 Microsoft YaHei;}}\f0\fs21 "]
    for kind, v in c.doc_blocks():
        if kind == "p":
            parts.append(_rtf_escape(v) + r"\par" + "\n")
            continue
        ncol = max(len(r) for r in v)
        cw = 9600 // ncol
        border = r"\clbrdrt\brdrs\brdrw10\clbrdrl\brdrs\brdrw10\clbrdrb\brdrs\brdrw10\clbrdrr\brdrs\brdrw10"
        for row in v:
            spans = _merge_spans(row, ncol)
            defs = "".join(border + r"\cellx%d" % (cw * (k + 1)) for j, k, _ in spans)
            cells = "".join(r"\pard\intbl " + _rtf_escape(val).replace("\n", r"\line ") + r"\cell " for _, _, val in spans)
            parts.append(r"\trowd\trgaph80" + defs + cells + r"\row" + "\n")
        parts.append(r"\pard\par" + "\n")
    for img in c.doc_pictures():
        img = _limit(img, 1200)
        w_tw = int(min(6.0, img.width / 96) * 1440)
        h_tw = int(w_tw * img.height / img.width)
        hexdata = _png_bytes(img).hex()
        parts.append(r"{\pict\pngblip\picw%d\pich%d\picwgoal%d\pichgoal%d " % (img.width, img.height, w_tw, h_tw))
        parts.append("\n".join(hexdata[i:i + 128] for i in range(0, len(hexdata), 128)))
        parts.append(r"}\par" + "\n")
    parts.append("}")
    with open(path, "w", encoding="ascii") as f:
        f.write("".join(parts))


def _word_com_save(src_docx, dst, fileformat):
    """若本机装有 Microsoft Word，用它另存为真正的二进制 .doc/.dot。"""
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return False
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        try:
            d = word.Documents.Open(os.path.abspath(src_docx))
            d.SaveAs2(os.path.abspath(dst), FileFormat=fileformat)
            d.Close(False)
        finally:
            word.Quit()
        return True
    except Exception:
        return False


def write_doc(c, path, fmt):
    tmp = os.path.join(tempfile.mkdtemp(), "t.docx")
    write_docx(c, tmp)
    if _word_com_save(tmp, path, 0 if fmt == "DOC" else 1):
        return
    write_rtf(c, path)  # Word / WPS / LibreOffice 均可直接打开 RTF 内容的 .doc/.dot


def write_odt(c, path):
    from odf.opendocument import OpenDocumentText
    from odf.style import Style, TextProperties
    from odf.text import P
    from odf.draw import Frame, Image as DImage
    d = OpenDocumentText()
    s = Style(name="Body", family="paragraph")
    s.addElement(TextProperties(fontname="Microsoft YaHei", fontnameasian="Microsoft YaHei",
                                fontsize="10.5pt", fontsizeasian="10.5pt"))
    d.styles.addElement(s)
    from odf.table import Table, TableColumn, TableRow, TableCell, CoveredTableCell
    from odf.style import TableCellProperties
    cs = Style(name="Cell", family="table-cell")
    cs.addElement(TableCellProperties(border="0.5pt solid #000000", padding="0.05cm"))
    d.automaticstyles.addElement(cs)
    for kind, v in c.doc_blocks():
        if kind == "p":
            d.text.addElement(P(stylename=s, text=v))
            continue
        ncol = max(len(r) for r in v)
        tb = Table()
        tb.addElement(TableColumn(numbercolumnsrepeated=ncol))
        for row in v:
            tr_ = TableRow()
            for j, k, val in _merge_spans(row, ncol):
                cell = TableCell(stylename=cs, valuetype="string", numbercolumnsspanned=k - j + 1)
                for ln in val.split("\n"):
                    cell.addElement(P(stylename=s, text=ln))
                tr_.addElement(cell)
                for _ in range(k - j):
                    tr_.addElement(CoveredTableCell())
            tb.addElement(tr_)
        d.text.addElement(tb)
        d.text.addElement(P(stylename=s, text=""))
    for i, img in enumerate(c.doc_pictures()):
        img = _limit(img)
        href = d.addPicture(f"Pictures/img{i}.png", "image/png", _png_bytes(img))
        w = min(16.0, img.width / 96 * 2.54)
        h = w * img.height / img.width
        p = P()
        fr = Frame(width=f"{w:.2f}cm", height=f"{h:.2f}cm", anchortype="as-char")
        fr.addElement(DImage(href=href))
        p.addElement(fr)
        d.text.addElement(p)
    d.save(path)


def write_xps(c, path, oxps=False):
    pages = [_limit(p, 1240) for p in c.page_images()]
    z = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED)
    if oxps:  # OpenXPS（ECMA-388）与 XPS 结构相同，只是命名空间不同
        raw = z.writestr
        z.writestr = lambda n, d: raw(n, d.replace("http://schemas.microsoft.com/xps/2005/06",
                                                   "http://schemas.openxps.org/oxps/v1.0") if isinstance(d, str) else d)
    z.writestr("[Content_Types].xml",
               '<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
               '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
               '<Default Extension="fdseq" ContentType="application/vnd.ms-package.xps-fixeddocumentsequence+xml"/>'
               '<Default Extension="fdoc" ContentType="application/vnd.ms-package.xps-fixeddocument+xml"/>'
               '<Default Extension="fpage" ContentType="application/vnd.ms-package.xps-fixedpage+xml"/>'
               '<Default Extension="png" ContentType="image/png"/></Types>')
    z.writestr("_rels/.rels",
               '<?xml version="1.0" encoding="utf-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               '<Relationship Id="R0" Type="http://schemas.microsoft.com/xps/2005/06/fixedrepresentation" Target="/FixedDocSeq.fdseq"/></Relationships>')
    z.writestr("FixedDocSeq.fdseq",
               '<FixedDocumentSequence xmlns="http://schemas.microsoft.com/xps/2005/06"><DocumentReference Source="/Documents/1/FixedDoc.fdoc"/></FixedDocumentSequence>')
    refs = "".join(f'<PageContent Source="/Documents/1/Pages/{i}.fpage"/>' for i in range(1, len(pages) + 1))
    z.writestr("Documents/1/FixedDoc.fdoc", f'<FixedDocument xmlns="http://schemas.microsoft.com/xps/2005/06">{refs}</FixedDocument>')
    for i, img in enumerate(pages, 1):
        W = 816
        H = round(W * img.height / img.width, 2)
        z.writestr(f"Resources/img{i}.png", _png_bytes(img.convert("RGB")))
        z.writestr(f"Documents/1/Pages/{i}.fpage",
                   f'<FixedPage xmlns="http://schemas.microsoft.com/xps/2005/06" Width="{W}" Height="{H}" xml:lang="zh-CN">'
                   f'<Path Data="M 0,0 L {W},0 {W},{H} 0,{H} z"><Path.Fill>'
                   f'<ImageBrush ImageSource="/Resources/img{i}.png" Viewbox="0,0,{img.width},{img.height}" '
                   f'ViewboxUnits="Absolute" Viewport="0,0,{W},{H}" ViewportUnits="Absolute"/>'
                   f'</Path.Fill></Path></FixedPage>')
        z.writestr(f"Documents/1/Pages/_rels/{i}.fpage.rels",
                   '<?xml version="1.0" encoding="utf-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   f'<Relationship Id="R{i}" Type="http://schemas.microsoft.com/xps/2005/06/required-resource" Target="/Resources/img{i}.png"/></Relationships>')
    z.close()


def write_djvu(c, path):
    c44 = shutil.which("c44")
    djvm = shutil.which("djvm")
    for base in (r"C:\Program Files (x86)\DjVuLibre", r"C:\Program Files\DjVuLibre"):
        if not c44 and os.path.exists(os.path.join(base, "c44.exe")):
            c44, djvm = os.path.join(base, "c44.exe"), os.path.join(base, "djvm.exe")
    if not c44:
        raise RuntimeError("DJVU 需要安装 DjVuLibre（c44/djvm），可从 djvu.sourceforge.net 获取")
    tmp = tempfile.mkdtemp()
    parts = []
    for i, img in enumerate(c.page_images()):
        ppm = os.path.join(tmp, f"{i}.ppm")
        img.convert("RGB").save(ppm)
        out = os.path.join(tmp, f"{i}.djvu")
        subprocess.run([c44, "-dpi", "150", ppm, out], check=True, creationflags=0x08000000)
        parts.append(out)
    if len(parts) == 1:
        shutil.copy(parts[0], path)
    else:
        subprocess.run([djvm, "-c", path, *parts], check=True, creationflags=0x08000000)


def write_abw(c, path):
    body, data = [], []
    for t in c.text:
        body.append(f"<p>{escape(t)}</p>")
    for i, img in enumerate(c.doc_pictures()):
        img = _limit(img)
        w = min(6.0, img.width / 96)
        h = w * img.height / img.width
        body.append(f'<p><image dataid="img{i}" props="width:{w:.2f}in; height:{h:.2f}in"/></p>')
        data.append(f'<d name="img{i}" mime-type="image/png" base64="yes">{base64.b64encode(_png_bytes(img)).decode()}</d>')
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE abiword PUBLIC "-//ABISOURCE//DTD AWML 1.0 Strict//EN" '
           '"http://www.abisource.com/awml.dtd">\n<abiword xmlns="http://www.abisource.com/awml.dtd" version="1.0" fileformat="1.0">'
           f'<metadata><m key="dc.title">{escape(c.title)}</m></metadata>'
           '<styles><s type="P" name="Normal" props="font-family:Microsoft YaHei; font-size:11pt"/></styles>'
           f'<section>{"".join(body)}</section>'
           + (f'<data>{"".join(data)}</data>' if data else "") + "</abiword>")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


def write_kwd(c, path):
    paras = "".join(f'<PARAGRAPH><TEXT xml:space="preserve">{escape(t)}</TEXT>'
                    f'<LAYOUT><NAME value="Standard"/></LAYOUT></PARAGRAPH>' for t in (c.text or [""]))
    maindoc = ('<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE DOC>'
               '<DOC editor="KWord" mime="application/x-kword" syntaxVersion="2">'
               '<PAPER format="1" width="595" height="841" orientation="0" columns="1" hType="0" fType="0">'
               '<PAPERBORDERS left="56" top="56" right="56" bottom="56"/></PAPER>'
               '<ATTRIBUTES processing="0" standardpage="1" hasHeader="0" hasFooter="0"/>'
               '<FRAMESETS><FRAMESET frameType="1" frameInfo="0" name="Text Frameset 1" visible="1">'
               '<FRAME left="56" top="56" right="539" bottom="785" runaround="1" autoCreateNewFrame="1" newFrameBehavior="0"/>'
               f'{paras}</FRAMESET></FRAMESETS>'
               '<STYLES><STYLE><NAME value="Standard"/><FORMAT><FONT name="Microsoft YaHei"/><SIZE value="11"/></FORMAT></STYLE></STYLES></DOC>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/x-kword")
        z.writestr("maindoc.xml", maindoc)
        z.writestr("documentinfo.xml", f'<?xml version="1.0" encoding="UTF-8"?><document-info><about><title>{escape(c.title)}</title></about></document-info>')


def write_dbk(c, path):
    pics = c.doc_pictures()
    items = [f"<para>{escape(t)}</para>" for t in c.text]
    if pics:
        imgdir = os.path.splitext(path)[0] + "_images"
        os.makedirs(imgdir, exist_ok=True)
        for i, img in enumerate(pics, 1):
            fn = f"image{i:03d}.png"
            _limit(img).save(os.path.join(imgdir, fn))
            items.append(f'<mediaobject><imageobject><imagedata fileref="{os.path.basename(imgdir)}/{fn}"/></imageobject></mediaobject>')
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<article xmlns="http://docbook.org/ns/docbook" version="5.0" xml:lang="zh-CN">'
           f'<info><title>{escape(c.title)}</title></info>\n' + "\n".join(items) + "\n</article>")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


def write_sxw(c, path):
    """OpenOffice.org 1.x Writer 文档（仅文字）。"""
    ns = ('xmlns:office="http://openoffice.org/2000/office" xmlns:style="http://openoffice.org/2000/style" '
          'xmlns:text="http://openoffice.org/2000/text" xmlns:fo="http://www.w3.org/1999/XSL/Format"')
    paras = "".join(f'<text:p text:style-name="Standard">{escape(t)}</text:p>' for t in (c.text or [c.title]))
    content = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ns} office:class="text" '
               f'office:version="1.0"><office:body>{paras}</office:body></office:document-content>')
    styles = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-styles {ns} office:version="1.0"><office:styles>'
              '<style:style style:name="Standard" style:family="paragraph"><style:properties '
              'style:font-name="Microsoft YaHei" style:font-name-asian="Microsoft YaHei" fo:font-size="11pt"/>'
              '</style:style></office:styles></office:document-styles>')
    manifest = ('<?xml version="1.0" encoding="UTF-8"?><manifest:manifest xmlns:manifest="http://openoffice.org/2001/manifest">'
                '<manifest:file-entry manifest:media-type="application/vnd.sun.xml.writer" manifest:full-path="/"/>'
                '<manifest:file-entry manifest:media-type="text/xml" manifest:full-path="content.xml"/>'
                '<manifest:file-entry manifest:media-type="text/xml" manifest:full-path="styles.xml"/>'
                '</manifest:manifest>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.sun.xml.writer")
        z.writestr("content.xml", content)
        z.writestr("styles.xml", styles)
        z.writestr("META-INF/manifest.xml", manifest)


def _tables_for_sheet(c):
    """内容 → [(工作表名, 行列表)]；表格逐个成表，表格外的文字单独放一张「文本」表。"""
    sheets, texts = [], []
    for kind, v in c.doc_blocks():
        if kind == "table":
            sheets.append((f"表{len(sheets) + 1}", v))
        else:
            texts.append([v])
    if texts:
        sheets.append(("文本", texts))
    return sheets or [("Sheet1", [[c.title]])]


def write_sheet(c, path, fmt):
    sheets = _tables_for_sheet(c)
    if fmt == "CSV":
        import csv
        rows = []
        for i, (name, v) in enumerate(sheets):
            if i:
                rows.append([])
            rows += [[x or "" for x in r] for r in v]
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(rows)
        return
    import openpyxl
    from openpyxl.styles import Alignment, Border, Side, Font
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    thin = Side(style="thin", color="000000")
    for name, v in sheets:
        ws = wb.create_sheet(name[:31])
        ncol = max(len(r) for r in v)
        widths = [8] * ncol
        for i, r in enumerate(v, 1):
            for j, k, val in _merge_spans(r, ncol):
                cell = ws.cell(i, j + 1)
                num = val.replace(",", "")
                try:  # 数字按数字写入，便于在 Excel 里计算
                    cell.value = int(num) if num.isdigit() else float(num) if num.replace(".", "", 1).lstrip("-").isdigit() else val
                except ValueError:
                    cell.value = val
                cell.alignment = Alignment(wrap_text=True, vertical="center")
                cell.font = Font(name="微软雅黑", size=10)
                if name != "文本":
                    for col in range(j + 1, k + 2):
                        ws.cell(i, col).border = Border(left=thin, right=thin, top=thin, bottom=thin)
                if k > j:
                    ws.merge_cells(start_row=i, start_column=j + 1, end_row=i, end_column=k + 1)
                    cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
                else:
                    longest = max((sum(2 if ord(ch) > 0x2E80 else 1 for ch in ln) for ln in val.split("\n")), default=0)
                    widths[j] = max(widths[j], min(longest + 2, 60))
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w
    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    if fmt == "XLSM":  # 启用宏的工作簿：内容类型必须是 macroEnabled，否则 Excel 拒绝打开
        src, out = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for it in src.infolist():
                b = src.read(it)
                if it.filename == "[Content_Types].xml":
                    b = b.replace(b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
                                  b"application/vnd.ms-excel.sheet.macroEnabled.main+xml")
                z.writestr(it, b)
        data = out.getvalue()
    with open(path, "wb") as f:
        f.write(data)


def write_document(c, out_base, fmt):
    path = out_base + "." + fmt.lower()
    if fmt == "PDF":
        write_pdf(c, path)
    elif fmt in DOCX_CT:
        write_docx(c, path, fmt)
    elif fmt in ("DOC", "DOT"):
        write_doc(c, path, fmt)
    elif fmt == "RTF":
        write_rtf(c, path)
    elif fmt == "ODT":
        write_odt(c, path)
    elif fmt in ("XPS", "OXPS"):
        write_xps(c, path, oxps=fmt == "OXPS")
    elif fmt == "SXW":
        write_sxw(c, path)
    elif fmt == "DJVU":
        write_djvu(c, path)
    elif fmt in ("ABW", "AW"):
        write_abw(c, path)  # .aw 采用 AbiWord 兼容格式
    elif fmt == "KWD":
        write_kwd(c, path)
    elif fmt == "DBK":
        write_dbk(c, path)
    else:
        raise ValueError(fmt)
    return [path]


def _unique_base(out_dir, title, ext):
    """同一天同名文件不覆盖，依次加 (2)、(3)…"""
    base, n = os.path.join(out_dir, title), 1
    while os.path.exists(base + ext) or os.path.exists(base + "_001" + ext):
        n += 1
        base = os.path.join(out_dir, f"{title} ({n})")
    return base


def convert(src, out_dir, fmt, kind=None):
    """kind 为 "image" / "doc" / "vector"；SVG 同时出现在图像与向量两类里，用 kind 区分。"""
    c = load(src)
    kind = kind or ("image" if fmt in IMAGE_FORMATS else "doc" if fmt in DOC_FORMATS
                    else "sheet" if fmt in SHEET_FORMATS else "vector")
    base = _unique_base(out_dir, c.title, ext_of(fmt))
    if kind == "image":
        return write_images(c, base, fmt)
    if kind == "sheet":
        write_sheet(c, base + ext_of(fmt), fmt)
        return [base + ext_of(fmt)]
    if kind == "vector":
        import vector
        return vector.write_vector(c, base, fmt, src)
    return write_document(c, base, fmt)
