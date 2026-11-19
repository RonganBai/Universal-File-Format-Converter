"""视频转换：基于 PyAV（内置 FFmpeg）重新编码或仅换封装。

容器（扩展名）与编码分开选择：编码决定兼容性与画质，容器决定能装哪些编码。
所选编码与容器不兼容时自动改用该容器的默认编码，并在结果里说明。
"""
from __future__ import annotations

import os
from fractions import Fraction

VIDEO_FORMATS = ["MP4", "MOV", "MKV", "WEBM", "AVI", "WMV", "FLV", "TS", "MTS", "M2TS",
                 "MPG", "MPEG", "3GP", "VOB"]

# 编码键 → (显示名, FFmpeg 编码器, 像素格式)
CODECS = {
    "h264": ("H.264 / AVC", "libx264", "yuv420p"),
    "hevc": ("H.265 / HEVC", "libx265", "yuv420p"),
    "av1": ("AV1", "libsvtav1", "yuv420p"),
    "vp9": ("VP9", "libvpx-vp9", "yuv420p"),
    "vp8": ("VP8", "libvpx", "yuv420p"),
    "prores": ("ProRes 422 HQ", "prores_ks", "yuv422p10le"),
    "dnxhr": ("DNxHR HQ", "dnxhd", "yuv422p"),
    "mpeg2": ("MPEG-2", "mpeg2video", "yuv420p"),
    "mjpeg": ("MJPEG", "mjpeg", "yuvj420p"),
    # 仅作部分容器的默认编码，不在界面单独列出
    "mpeg4": ("MPEG-4 Part 2", "mpeg4", "yuv420p"),
    "wmv2": ("WMV8", "wmv2", "yuv420p"),
}
# 界面可选的编码（顺序即显示顺序）；"auto" 用容器默认，"copy" 不重新编码
CODEC_CHOICES = [("auto", "自动（按格式推荐）"), ("h264", "H.264 / AVC（通用）"), ("hevc", "H.265 / HEVC"),
                 ("av1", "AV1"), ("vp9", "VP9"), ("vp8", "VP8"), ("prores", "ProRes 422 HQ"),
                 ("dnxhr", "DNxHR HQ"), ("mpeg2", "MPEG-2"), ("mjpeg", "MJPEG"),
                 ("copy", "保持原编码（只换封装，最快）")]

# 容器 → (FFmpeg 封装格式, 默认编码, 允许的编码, 音频编码器, 音频采样率, 额外封装选项)
_ALL = {"h264", "hevc", "av1", "vp9", "vp8", "prores", "dnxhr", "mpeg2", "mjpeg", "mpeg4"}
_TS = ("mpegts", "h264", {"h264", "hevc", "mpeg2"}, "aac", 48000, {})
CONTAINERS = {
    "MP4": ("mp4", "h264", {"h264", "hevc", "av1", "vp9", "mpeg2", "mjpeg", "mpeg4"}, "aac", 48000,
            {"movflags": "+faststart"}),
    "MOV": ("mov", "h264", {"h264", "hevc", "av1", "prores", "dnxhr", "mjpeg", "mpeg2", "mpeg4"}, "aac", 48000,
            {"movflags": "+faststart"}),
    "MKV": ("matroska", "h264", _ALL, "aac", 48000, {}),
    "WEBM": ("webm", "vp9", {"vp9", "vp8", "av1"}, "libopus", 48000, {}),
    "AVI": ("avi", "mpeg4", {"mpeg4", "h264", "mjpeg", "mpeg2", "dnxhr"}, "libmp3lame", 44100, {}),
    "WMV": ("asf", "wmv2", {"wmv2"}, "wmav2", 44100, {}),
    "FLV": ("flv", "h264", {"h264"}, "aac", 44100, {}),
    "TS": _TS,
    "MTS": ("mpegts", "h264", {"h264", "hevc", "mpeg2"}, "ac3", 48000, {"mpegts_m2ts_mode": "1"}),
    "M2TS": ("mpegts", "h264", {"h264", "hevc", "mpeg2"}, "ac3", 48000, {"mpegts_m2ts_mode": "1"}),
    "MPG": ("mpeg", "mpeg2", {"mpeg2"}, "mp2", 48000, {}),
    "MPEG": ("mpeg", "mpeg2", {"mpeg2"}, "mp2", 48000, {}),
    "3GP": ("3gp", "h264", {"h264"}, "aac", 44100, {}),
    "VOB": ("vob", "mpeg2", {"mpeg2"}, "ac3", 48000, {}),
}
# 源流编码名 → 编码键（用于「保持原编码」判断能否直接放进目标容器）
_SRC_KEY = {"h264": "h264", "hevc": "hevc", "av1": "av1", "vp9": "vp9", "vp8": "vp8", "prores": "prores",
            "dnxhd": "dnxhr", "mpeg2video": "mpeg2", "mjpeg": "mjpeg", "mpeg4": "mpeg4", "wmv2": "wmv2"}
_AUDIO_OK = {  # 容器能直接装下的源音频编码（只换封装时使用）
    "mp4": {"aac", "mp3", "ac3", "eac3", "opus", "alac", "flac"}, "mov": {"aac", "mp3", "ac3", "alac", "pcm_s16le"},
    "matroska": None, "webm": {"opus", "vorbis"}, "avi": {"mp3", "ac3", "pcm_s16le", "mp2"},
    "asf": {"wmav2", "wmav1", "mp3"}, "flv": {"aac", "mp3"}, "mpegts": {"aac", "ac3", "mp2", "mp3", "eac3"},
    "mpeg": {"mp2", "mp3", "ac3"}, "3gp": {"aac", "amr_nb"}, "vob": {"ac3", "mp2"},
}
_AUDIO_FRAME = {"aac": 1024, "libmp3lame": 1152, "libopus": 960, "ac3": 1536, "mp2": 1152, "wmav2": 2048}
_AUDIO_FMT = {"aac": "fltp", "libmp3lame": "s16p", "libopus": "s16", "ac3": "fltp", "mp2": "s16", "wmav2": "fltp"}
_ANAME = {"aac": "AAC", "libmp3lame": "MP3", "libopus": "Opus", "ac3": "AC-3", "mp2": "MP2", "wmav2": "WMA"}
_MPEG2_RATES = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001), Fraction(30),
                Fraction(50), Fraction(60000, 1001), Fraction(60)]


def ext_of(fmt):
    return "." + fmt.lower()


def codec_label(key):
    return dict(CODEC_CHOICES).get(key) or CODECS.get(key, (key,))[0]


def _pick_rate(st, key, fmt):
    r = st.average_rate or st.guessed_rate or Fraction(25)
    r = Fraction(r).limit_denominator(1001)
    if r <= 0 or r > 240:
        r = Fraction(25)
    if key == "mpeg2" or fmt in ("VOB", "MPG", "MPEG"):
        r = min(_MPEG2_RATES, key=lambda x: abs(x - r))
    return r


def _size(w, h, max_side, key):
    if max_side and max(w, h) > max_side:
        s = max_side / max(w, h)
        w, h = w * s, h * s
    w, h = max(2, int(round(w / 2)) * 2), max(2, int(round(h / 2)) * 2)
    return w, h


def _video_options(key, w, h, rate, quality):
    """返回 (codec options, bit_rate)；quality 0-100（0 = 默认）。"""
    q = quality or 0
    px = w * h * float(rate)
    if key == "h264":
        return {"crf": str(int(round(51 - q * 0.33))) if q else "21", "preset": "medium"}, None
    if key == "hevc":
        return {"crf": str(int(round(51 - q * 0.3))) if q else "26", "preset": "medium",
                "x265-params": "log-level=error"}, None
    if key == "av1":
        return {"crf": str(int(round(63 - q * 0.45))) if q else "32", "preset": "8"}, None
    if key in ("vp9", "vp8"):
        o = {"crf": str(int(round(63 - q * 0.45))) if q else "31", "deadline": "good", "cpu-used": "4"}
        return o, (0 if key == "vp9" else int(px * 0.15))
    if key == "prores":
        return {"profile": "3"}, None
    if key == "dnxhr":
        return {"profile": "dnxhr_hq"}, None
    bpp = {"mpeg2": 0.25, "mpeg4": 0.18, "wmv2": 0.2, "mjpeg": 1.2}[key] * ((q / 70) if q else 1)
    br = int(min(max(px * bpp, 500_000), 9_000_000 if key == "mpeg2" else 80_000_000))
    return {}, br


def transcode(src, base, fmt, codec="auto", params=None, strip_meta=True):
    """把 src 转为 fmt 容器；返回 (输出路径, notes, level)。"""
    import av

    params = params or {}
    container, default, allowed, aenc, arate, mux_opts = CONTAINERS[fmt]
    notes, level = [], "full"
    out_path = base + ext_of(fmt)

    def note(msg, lv=None):
        nonlocal level
        notes.append(msg)
        if lv == "partial":
            level = "partial"

    inp = av.open(src)
    try:
        if not inp.streams.video:
            raise ValueError("没有找到视频画面（纯音频文件不能转为视频格式）")
        vs = inp.streams.video[0]
        ain = inp.streams.audio[0] if inp.streams.audio else None
        if len(inp.streams.audio) > 1:
            note(f"源文件有 {len(inp.streams.audio)} 条音轨，只保留第 1 条", "partial")
        if inp.streams.subtitles:
            note("字幕轨未保留", "partial")

        src_name = vs.codec_context.name
        src_key = _SRC_KEY.get(src_name)
        copy_v = False
        if codec == "copy":
            if src_key in allowed or (container == "matroska" and src_key):
                copy_v = True
                key = src_key
            else:
                key = default
                note(f"{fmt} 不能直接装入 {src_name.upper()} 编码，已改为重新编码为 {CODECS[key][0]}", "partial")
        else:
            key = default if codec in (None, "", "auto") else codec
            if key not in allowed:
                note(f"{fmt} 不支持 {CODECS.get(key, (key,))[0]}，已改用 {CODECS[default][0]}", "partial")
                key = default

        out = av.open(out_path, "w", format=container, options=dict(mux_opts))
        try:
            if not strip_meta:
                for k, v in inp.metadata.items():
                    try:
                        out.metadata[k] = v
                    except Exception:
                        pass

            # ---- 视频流
            if copy_v:
                ovs = out.add_stream_from_template(vs)
                note(f"保持原 {src_name.upper()} 编码，只更换封装，画质无损")
            else:
                rate = _pick_rate(vs, key, fmt)
                w, h = _size(vs.codec_context.width, vs.codec_context.height, params.get("max_side"), key)
                enc, pix = CODECS[key][1], CODECS[key][2]
                opts, br = _video_options(key, w, h, rate, params.get("quality"))
                ovs = out.add_stream(enc, rate=rate, options=opts)
                ovs.width, ovs.height, ovs.pix_fmt = w, h, pix
                if br is not None:
                    ovs.bit_rate = br
                if key == "mpeg2":
                    ovs.codec_context.gop_size = 15
                if key == "hevc" and container in ("mp4", "mov"):
                    ovs.codec_tag = "hvc1"   # 让 Apple 设备与 QuickTime 能识别 HEVC
                note(f"视频编码：{CODECS[key][0]}，{w}×{h}，{float(rate):.3g} fps")
                if key in ("prores", "dnxhr"):
                    note("专业剪辑中间编码，文件会明显变大")

            # ---- 音频流
            oas, copy_a, resampler, fifo = None, False, None, None
            if ain is not None:
                ok = _AUDIO_OK.get(container, set())
                if copy_v and (ok is None or ain.codec_context.name in ok):
                    oas, copy_a = out.add_stream_from_template(ain), True
                else:
                    oas = out.add_stream(aenc, rate=arate)
                    oas.layout = "stereo" if (ain.codec_context.channels or 2) >= 2 or aenc == "ac3" else "mono"
                    if aenc in ("aac", "ac3", "mp2", "libmp3lame", "wmav2"):
                        oas.bit_rate = 192_000
                    resampler = av.AudioResampler(format=_AUDIO_FMT.get(aenc, "fltp"), layout=oas.layout.name,
                                                  rate=arate)
                    fifo = av.AudioFifo()

            # ---- 编码循环
            start = None
            nxt, n_out = 0.0, 0
            a_pts = 0
            fsize = _AUDIO_FRAME.get(aenc, 1024)
            streams = [vs] + ([ain] if ain is not None else [])

            def push_audio(frames):
                nonlocal a_pts
                for af in frames:
                    af.pts = None
                    fifo.write(af)
                while fifo.samples >= fsize:
                    f = fifo.read(fsize)
                    f.pts, f.time_base = a_pts, Fraction(1, arate)
                    a_pts += f.samples
                    for p in oas.encode(f):
                        out.mux(p)

            for pkt in inp.demux(*streams):
                if pkt.stream is vs:
                    if copy_v:
                        if pkt.dts is None:
                            continue
                        pkt.stream = ovs
                        out.mux(pkt)
                        continue
                    for fr in pkt.decode():
                        t = fr.time if fr.time is not None else n_out / float(rate)
                        if start is None:
                            start = t
                        t -= start
                        if t + 0.5 / float(rate) < nxt:
                            continue   # 源帧率高于目标：丢帧
                        rot = getattr(fr, "rotation", 0) or 0
                        if rot % 360:
                            import numpy as np
                            arr = np.rot90(fr.to_ndarray(format="rgb24"), k=(rot // 90) % 4)
                            fr = av.VideoFrame.from_ndarray(np.ascontiguousarray(arr), format="rgb24")
                            if (rot // 90) % 2 and n_out == 0:
                                ovs.width, ovs.height = _size(fr.width, fr.height, params.get("max_side"), key)
                        img = fr.reformat(width=ovs.width, height=ovs.height, format=ovs.pix_fmt)
                        while nxt <= t + 0.5 / float(rate):   # 源帧率低于目标：重复帧，保持恒定帧率
                            o = img if nxt == 0 else img.reformat()
                            o.pts, o.time_base = n_out, Fraction(1) / rate
                            for p in ovs.encode(o):
                                out.mux(p)
                            n_out += 1
                            nxt = n_out / float(rate)
                elif oas is not None:
                    if copy_a:
                        if pkt.dts is None:
                            continue
                        pkt.stream = oas
                        out.mux(pkt)
                    else:
                        for af in pkt.decode():
                            push_audio(resampler.resample(af))

            if not copy_v:
                for p in ovs.encode(None):
                    out.mux(p)
                if n_out == 0:
                    raise ValueError("视频没有可解码的画面")
            if oas is not None and not copy_a:
                push_audio(resampler.resample(None))
                if fifo.samples:
                    f = fifo.read()
                    f.pts, f.time_base = a_pts, Fraction(1, arate)
                    for p in oas.encode(f):
                        out.mux(p)
                for p in oas.encode(None):
                    out.mux(p)
            if ain is None:
                note("源视频没有音轨")
            elif not copy_a:
                note("音频编码：" + _ANAME.get(aenc, aenc.upper()))
        finally:
            out.close()
    except Exception:
        inp.close()
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except OSError:
                pass
        raise
    inp.close()
    if not strip_meta:
        note("已保留源文件的标题等元数据")
    return out_path, notes, level
