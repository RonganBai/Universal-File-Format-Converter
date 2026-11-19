# 格式转换器

**简体中文** · [English](README.en.md)

适用于 Windows 的桌面批量转换工具，支持图像、文档、电子表格、矢量图和视频。

## 下载安装

[查看最新发布](https://github.com/RonganBai/Universal-File-Format-Converter/releases/latest) · [浏览所有版本](https://github.com/RonganBai/Universal-File-Format-Converter/releases)

| 版本 | Windows x64 安装包 | 更新说明 |
| --- | --- | --- |
| v1.13.3 | [下载安装包](https://github.com/RonganBai/Universal-File-Format-Converter/releases/download/v1.13.3/FormatConverter-Setup-1.13.3.exe) | [查看发布](https://github.com/RonganBai/Universal-File-Format-Converter/releases/tag/v1.13.3) |
| v1.13.2 | [下载安装包](https://github.com/RonganBai/Universal-File-Format-Converter/releases/download/v1.13.2/FormatConverter-Setup-1.13.2.exe) | [查看发布](https://github.com/RonganBai/Universal-File-Format-Converter/releases/tag/v1.13.2) |
| v1.13.1 | [下载安装包](https://github.com/RonganBai/Universal-File-Format-Converter/releases/download/v1.13.1/FormatConverter-Setup-1.13.1.exe) | [查看发布](https://github.com/RonganBai/Universal-File-Format-Converter/releases/tag/v1.13.1) |
| v1.13.0 | [下载安装包](https://github.com/RonganBai/Universal-File-Format-Converter/releases/download/v1.13.0/FormatConverter-Setup-1.13.0.exe) | [查看发布](https://github.com/RonganBai/Universal-File-Format-Converter/releases/tag/v1.13.0) |
| v1.12.1 | [下载安装包](https://github.com/RonganBai/Universal-File-Format-Converter/releases/download/v1.12.1/FormatConverter-Setup-1.12.1.exe) | [查看发布](https://github.com/RonganBai/Universal-File-Format-Converter/releases/tag/v1.12.1) |
| v1.12.0 | [下载安装包](https://github.com/RonganBai/Universal-File-Format-Converter/releases/download/v1.12.0/FormatConverter-Setup-1.12.0.exe) | [查看发布](https://github.com/RonganBai/Universal-File-Format-Converter/releases/tag/v1.12.0) |
| v1.11.1 | [下载安装包](https://github.com/RonganBai/Universal-File-Format-Converter/releases/download/v1.11.1/FormatConverter-Setup-1.11.1.exe) | [查看发布](https://github.com/RonganBai/Universal-File-Format-Converter/releases/tag/v1.11.1) |
| v1.11.0 | [下载安装包](https://github.com/RonganBai/Universal-File-Format-Converter/releases/download/v1.11.0/FormatConverter-Setup-1.11.0.exe) | [查看发布](https://github.com/RonganBai/Universal-File-Format-Converter/releases/tag/v1.11.0) |
| v1.10.1 | [下载安装包](https://github.com/RonganBai/Universal-File-Format-Converter/releases/download/v1.10.1/FormatConverter-Setup-1.10.1.exe) | [查看发布](https://github.com/RonganBai/Universal-File-Format-Converter/releases/tag/v1.10.1) |
| v1.10.0 | [下载安装包](https://github.com/RonganBai/Universal-File-Format-Converter/releases/download/v1.10.0/FormatConverter-Setup-1.10.0.exe) | [查看发布](https://github.com/RonganBai/Universal-File-Format-Converter/releases/tag/v1.10.0) |
| v1.9.0 | [下载安装包](https://github.com/RonganBai/Universal-File-Format-Converter/releases/download/v1.9.0/FormatConverter-Setup-1.9.0.exe) | [查看发布](https://github.com/RonganBai/Universal-File-Format-Converter/releases/tag/v1.9.0) |

## 快速开始

1. 运行安装包，安装后打开「格式转换器」。
2. 拖入文件或文件夹，也可以点「添加文件」。
3. 选择目标格式开始转换。结果默认保存到用户目录下的 `格式转换输出\日期`，可在「设置 → 常规」修改。
4. 首次启动时可选择简体中文或 English。之后可点击窗口标题栏的「EN / 中文」切换语言，选择会自动保存。

## 功能

- 批量转换 PNG、JPEG、WEBP、GIF、ICO、TIFF、HEIC、AVIF、PDF、DOCX、ODT、RTF、SVG、AI、EPS、WMF 等格式。
- 视频支持 MP4、MOV、MKV、WEBM、AVI、WMV、FLV、TS、MTS、M2TS、MPG、MPEG、3GP 和 VOB。可选 H.264、H.265/HEVC、AV1、VP9、VP8、ProRes 422 HQ、DNxHR HQ、MPEG-2、MJPEG，或保留原编码只换封装。编码与容器不兼容时，程序会采用推荐编码并在结果中说明。
- 预设可保存常用转换配置，包括视频编码和最长边。任务和历史页面可查看转换进度与结果。
- 悬浮球支持拖入文件或文件夹、最多六种快捷格式、屏幕边缘吸附和后台常驻。右键可打开主窗口、设置或输出目录，也可退出程序。
- 可切换浅色和深色模式，并自定义背景色与强调色。

## 从源码运行

需要 Windows 10/11 和 Python 3.10 或更高版本。

```powershell
python -m pip install -r requirements.txt
python app.py
```

## 构建安装包

安装 Inno Setup 6 后，在 PowerShell 中运行：

```powershell
.\build.ps1
```

PyInstaller 打包应用，Inno Setup 生成 `installer/Output/` 下的安装包。DJVU 需要 DjVuLibre，JBG 需要将 JBIG-KIT 的 `pbmtojbg.exe` 加入 PATH。

## 许可证

暂未声明许可证。
