"""矢量格式写出：SVG / AI / PS / EPS / EMF / WMF / PLT / SK / SK1 / FIG / CGM。

思路：先把内容变成 PDF（PDF 源文件直接用原件，文字会被排成真正的矢量文字），
SVG 与 AI 由 PDF 直接得到真矢量；其余格式把页面渲染后：
  · PS / EPS / EMF / WMF / CGM —— 以高质量位图嵌入矢量容器
  · PLT / SK / SK1 / FIG —— 把黑白抖动后的像素合并成矢量线段/矩形（可直接用于绘图仪、切割机）
"""
import base64
import ctypes
import io
import os
import struct
import tempfile
import zlib
from ctypes import wintypes

import numpy as np
import pymupdf
from PIL import Image

import converter

DPI = 150


# ---------------------------------------------------------------- 内容 → PDF / 页面图像

def _pdf_bytes(c, src):
    ext = os.path.splitext(src)[1].lower().lstrip(".")
    with open(src, "rb") as f:
        raw = f.read()
    if ext == "pdf":
        return raw
    if ext in ("xps", "oxps", "epub", "mobi", "fb2", "cbz", "svg"):
        return pymupdf.open(stream=raw, filetype=ext).convert_to_pdf()
    if c.text:
        tmp = os.path.join(tempfile.mkdtemp(), "t.pdf")
        converter.write_pdf(c, tmp)
        with open(tmp, "rb") as f:
            return f.read()
    doc = pymupdf.open()  # 纯图片：页面大小与图片一致
    for img in c.page_images():
        img = converter._limit(img, 3000)
        w, h = img.width * 72 / DPI, img.height * 72 / DPI
        page = doc.new_page(width=w, height=h)
        page.insert_image(page.rect, stream=converter._png_bytes(img))
    return doc.tobytes(deflate=True)


def _pages(pdf, dpi=DPI):
    out = []
    for i, page in enumerate(pymupdf.open(stream=pdf, filetype="pdf")):
        if i >= 200:
            break
        pix = page.get_pixmap(dpi=dpi)
        out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return out


def _runs(img, maxw=900):
    """黑白抖动后，把每行连续的黑色像素合并为 (y, x0, x1)。"""
    g = img.convert("L")
    if g.width > maxw:
        g = g.resize((maxw, round(g.height * maxw / g.width)), Image.LANCZOS)
    a = np.asarray(g.convert("1"), dtype=bool) == False  # True = 黑
    runs = []
    for y, row in enumerate(a):
        d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        runs += [(y, int(s), int(e)) for s, e in zip(starts, ends)]
    return g.width, g.height, runs


# ---------------------------------------------------------------- 各格式

def _ps_page(img, eps=False):
    w, h = img.size
    pw, ph = w * 72 / DPI, h * 72 / DPI
    data = base64.a85encode(zlib.compress(img.tobytes(), 9), wrapcol=76).decode() + "~>"
    return (f"gsave {pw:.2f} {ph:.2f} scale /DeviceRGB setcolorspace\n"
            f"<< /ImageType 1 /Width {w} /Height {h} /BitsPerComponent 8 /Decode [0 1 0 1 0 1]\n"
            f"   /ImageMatrix [{w} 0 0 -{h} 0 {h}]\n"
            f"   /DataSource currentfile /ASCII85Decode filter /FlateDecode filter >> image\n"
            f"{data}\ngrestore\n"), pw, ph


def write_ps(pages, path, eps=False):
    if eps:
        pages = pages[:1]
    body, maxw, maxh = [], 0, 0
    for i, img in enumerate(pages, 1):
        s, pw, ph = _ps_page(img)
        maxw, maxh = max(maxw, pw), max(maxh, ph)
        if eps:
            body.append(s)
        else:
            body.append(f"%%Page: {i} {i}\n<< /PageSize [{pw:.2f} {ph:.2f}] >> setpagedevice\n{s}showpage\n")
    head = ("%!PS-Adobe-3.0 EPSF-3.0\n" if eps else "%!PS-Adobe-3.0\n")
    head += (f"%%Creator: 格式转换器\n%%BoundingBox: 0 0 {int(maxw + .99)} {int(maxh + .99)}\n"
             f"%%LanguageLevel: 3\n%%Pages: {len(pages)}\n%%EndComments\n")
    with open(path, "w", encoding="latin-1", errors="replace") as f:
        f.write(head + "".join(body) + "%%EOF\n")


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


def _emf_handle(img):
    gdi = ctypes.windll.gdi32
    gdi.CreateEnhMetaFileW.restype = wintypes.HDC
    gdi.CloseEnhMetaFile.restype = wintypes.HANDLE
    gdi.CloseEnhMetaFile.argtypes = [wintypes.HDC]
    gdi.StretchDIBits.argtypes = [wintypes.HDC] + [ctypes.c_int] * 8 + [ctypes.c_void_p, ctypes.c_void_p,
                                                                       wintypes.UINT, wintypes.DWORD]
    w, h = img.size
    rect = wintypes.RECT(0, 0, int(w / DPI * 2540), int(h / DPI * 2540))  # 0.01 mm
    hdc = gdi.CreateEnhMetaFileW(None, None, ctypes.byref(rect), None)
    stride = (w * 3 + 3) & ~3
    a = np.zeros((h, stride), np.uint8)
    a[:, :w * 3] = np.asarray(img.convert("RGB"))[::-1, :, ::-1].reshape(h, w * 3)  # 自底向上 BGR
    bih = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, h, 1, 24, 0, a.size, 0, 0, 0, 0)
    buf = a.tobytes()
    gdi.StretchDIBits(hdc, 0, 0, w, h, 0, 0, w, h, buf, ctypes.byref(bih), 0, 0x00CC0020)
    return gdi.CloseEnhMetaFile(hdc), w, h


def write_emf(img, path):
    gdi = ctypes.windll.gdi32
    gdi.GetEnhMetaFileBits.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p]
    gdi.DeleteEnhMetaFile.argtypes = [wintypes.HANDLE]
    hemf, _, _ = _emf_handle(img)
    n = gdi.GetEnhMetaFileBits(hemf, 0, None)
    buf = ctypes.create_string_buffer(n)
    gdi.GetEnhMetaFileBits(hemf, n, buf)
    gdi.DeleteEnhMetaFile(hemf)
    with open(path, "wb") as f:
        f.write(buf.raw)


def write_wmf(img, path):
    gdi, user = ctypes.windll.gdi32, ctypes.windll.user32
    gdi.GetWinMetaFileBits.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p, ctypes.c_int, wintypes.HDC]
    gdi.DeleteEnhMetaFile.argtypes = [wintypes.HANDLE]
    user.GetDC.restype = wintypes.HDC
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    hemf, w, h = _emf_handle(img)
    hdc = user.GetDC(None)
    n = gdi.GetWinMetaFileBits(hemf, 0, None, 8, hdc)  # MM_ANISOTROPIC
    buf = ctypes.create_string_buffer(n)
    gdi.GetWinMetaFileBits(hemf, n, buf, 8, hdc)
    user.ReleaseDC(None, hdc)
    gdi.DeleteEnhMetaFile(hemf)
    # Aldus 可放置文件头，便于 Office/看图软件识别尺寸
    inch = 1440
    right, bottom = int(w / DPI * inch), int(h / DPI * inch)
    hdr = struct.pack("<IHhhhhHI", 0x9AC6CDD7, 0, 0, 0, right, bottom, inch, 0)
    chk = 0
    for (v,) in struct.iter_unpack("<H", hdr):
        chk ^= v
    with open(path, "wb") as f:
        f.write(hdr + struct.pack("<H", chk) + buf.raw)


def write_plt(img, path):
    w, h, runs = _runs(img)
    k = 40 * 25.4 * (img.width / DPI) / w  # HPGL：40 单位/mm
    out = ["IN;SP1;PU0,0;"]
    for y, x0, x1 in runs:
        yy = round((h - y) * k)
        out.append(f"PU{round(x0 * k)},{yy};PD{round(x1 * k)},{yy};")
    out.append("PU0,0;SP0;")
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(out))


def write_sk(img, path, sk1=False):
    w, h, runs = _runs(img)
    k = 72 * (img.width / DPI) / w  # 单位：pt
    out = ["##sK1 1 2" if sk1 else "##Sketch 1 2", "document()", "layout((%g,%g),0)" % (w * k, h * k),
           "layer('Layer 1',1,1,0,0,(0,0,0))", "fp((0,0,0))", "le()", "lw(1)"]
    for y, x0, x1 in runs:
        out.append(f"r({(x1 - x0) * k:.3f},0,0,{k:.3f},{x0 * k:.3f},{(h - y - 1) * k:.3f})")
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(out) + "\n")


def write_fig(img, path):
    w, h, runs = _runs(img)
    k = 1200 * (img.width / DPI) / w  # 1200 单位/英寸
    out = ["#FIG 3.2  Produced by 格式转换器", "Portrait", "Center", "Metric", "A4", "100.00", "Single", "-2", "1200 2"]
    for y, x0, x1 in runs:
        X0, X1, Y0, Y1 = round(x0 * k), round(x1 * k), round(y * k), round((y + 1) * k)
        out.append(f"2 2 0 0 0 0 50 -1 20 0.000 0 0 -1 0 0 5\n\t{X0} {Y0} {X1} {Y0} {X1} {Y1} {X0} {Y1} {X0} {Y0}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def _cgm_el(cls, eid, data=b""):
    if len(data) % 2:
        data += b"\0"
    if len(data) < 31:
        return struct.pack(">H", (cls << 12) | (eid << 5) | len(data)) + data
    out = struct.pack(">H", (cls << 12) | (eid << 5) | 31)
    parts = [data[i:i + 32766] for i in range(0, len(data), 32766)]
    for i, p in enumerate(parts):
        out += struct.pack(">H", (0x8000 if i < len(parts) - 1 else 0) | len(p)) + p
    return out


def _cgm_str(s):
    b = s.encode("ascii", "replace")[:254]
    return bytes([len(b)]) + b


def write_cgm(pages, path, title):
    img = converter._limit(pages[0], 1400).convert("RGB")
    w, h = img.size
    a = np.asarray(img)
    row = w * 3
    pad = b"\0" * (row % 2)
    cells = b"".join(a[y].tobytes() + pad for y in range(h))
    out = _cgm_el(0, 1, _cgm_str(title))                         # BEGIN METAFILE
    out += _cgm_el(1, 1, struct.pack(">h", 1))                   # METAFILE VERSION
    out += _cgm_el(1, 11, struct.pack(">hhh", 1, -1, 1))         # ELEMENT LIST: 绘图集
    out += _cgm_el(0, 3, _cgm_str("page 1"))                     # BEGIN PICTURE
    out += _cgm_el(2, 2, struct.pack(">h", 1))                   # 颜色选择：直接色
    out += _cgm_el(2, 6, struct.pack(">hhhh", 0, 0, w, h))       # VDC EXTENT
    out += _cgm_el(0, 4)                                         # BEGIN PICTURE BODY
    out += _cgm_el(4, 9, struct.pack(">hhhhhhhhhh", 0, h, w, 0, w, h, w, h, 8, 1) + cells)  # CELL ARRAY
    out += _cgm_el(0, 5) + _cgm_el(0, 2)                         # END PICTURE / END METAFILE
    with open(path, "wb") as f:
        f.write(out)


# ---------------------------------------------------------------- 入口

def write_vector(c, base, fmt, src):
    ext = "." + fmt.lower()
    pdf = _pdf_bytes(c, src)
    if fmt == "AI":  # Illustrator 9+ 的 .ai 与 PDF 兼容
        with open(base + ext, "wb") as f:
            f.write(pdf)
        return [base + ext]
    if fmt == "SVG":
        doc = pymupdf.open(stream=pdf, filetype="pdf")
        n = min(doc.page_count, 200)
        outs = []
        for i in range(n):
            p = base + ext if n == 1 else f"{base}_{i + 1:03d}{ext}"
            with open(p, "w", encoding="utf-8") as f:
                f.write(doc[i].get_svg_image(text_as_path=True))
            outs.append(p)
        return outs
    pages = _pages(pdf)
    if fmt in ("PS", "EPS"):
        write_ps(pages, base + ext, eps=fmt == "EPS")
        return [base + ext]
    if fmt == "CGM":
        write_cgm(pages, base + ext, c.title)
        return [base + ext]
    one = {"EMF": write_emf, "WMF": write_wmf, "PLT": write_plt, "FIG": write_fig,
           "SK": write_sk, "SK1": lambda im, p: write_sk(im, p, sk1=True)}[fmt]
    outs = []
    for i, img in enumerate(pages):
        p = base + ext if len(pages) == 1 else f"{base}_{i + 1:03d}{ext}"
        one(img, p)
        outs.append(p)
    return outs
