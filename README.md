# DouyinLiveExporter

Windows 下的抖音评论实况图导出工具。从已开启 Root ADB 的 MuMu 模拟器读取新保存的缓存，生成苹果 Live Photo 配对资源；也支持转换本地 MP4/MOV。

## v4 功能

- 自动寻找 MuMu 安装目录中的 ADB，不限定安装盘符。
- 默认导出 HEIC（HEIF 容器）+ MOV，可选 JPG + MOV。
- 写入照片 Apple MakerNote、MOV 电影级配对标识及静态帧时间轨道。
- 使用 IMG_0001 等短文件名，每次导出放在独立目录。
- 保留原始缓存，转换失败不删除模拟器文件。
- 校验配对元数据及视频解码。

当前支持苹果配对格式；尚未实现安卓 Motion Photo。

## 使用

构建后运行 `dist/AppleLivePhoto_v4/DouyinLiveExporter.exe`。

1. 启动 MuMu，启用 Root ADB。
2. 选择 **1：监听并导出苹果 Live Photo**。
3. 在抖音评论区长按实况图并保存。
4. 在程序旁的 `DouyinLive/AppleLive` 查看结果。

开始监听前已有的缓存会被忽略。选择 **4** 可以转换已有 MP4/MOV，无需启动模拟器。监听时 Ctrl+C 返回菜单。选择 **2** 会删除模拟器缓存目录中的历史文件。

### 自动寻找 ADB

`adb_path` 默认留空。查找顺序为：手动覆盖配置（如有）、程序旁的 adb.exe、Windows 安装记录、MuMu 运行进程、常见安装目录、PATH。

兼容 nx_main、n_main、shell 及部分旧版目录布局。只查找已定位的安装目录和已知位置，不全盘扫描。特殊环境可将 `adb_path` 设置为 ADB 文件或 MuMu 安装目录。ADB 定位成功不代表 Root 或模拟器连接已启用。

## 导入 iPhone

HEIC/JPG 与同名 MOV 是一张 Live Photo 的配对资源，需要通过支持配对导入的工具保存到相册。

- Windows：可用爱思助手的「导入实况照片」，同时选择一对同名文件；已有用户反馈成功。
- macOS：可将配对文件导入「照片」，再同步到 iPhone。
- LocalSend、微信输入法等普通文件传输方式不保证将两个资源合并成 Live Photo。

相册中的最终名称由导入工具和 iOS 决定，源文件名不保证原样显示。不保证锁屏动态壁纸兼容性。

## 输出与画质

```text
DouyinLive/
  originals/                原始缓存备份，以内容哈希命名
  AppleLive/
    IMG_0001_唯一编号/
      IMG_0001.HEIC
      IMG_0001.MOV
      manifest.json
      导入说明.txt
```

默认截取视频开头最多 3 秒，输出 H.264、30 fps，有声音时转为 AAC。默认封面为输出视频中间帧，也可提供对应原图。视频和 HEIC 封面会重新编码，不宣称无损。程序不添加水印，也不移除素材原有的水印。

输入必须为实际 MP4/MOV 容器；静态图、其他混合格式或损坏缓存会报告错误。导出清单仅记录源文件名，不记录本机绝对路径。原始素材及导出结果应保持在本地，不提交到 Git。

## 配置

程序使用旁边的 `config.json`；从源码运行时使用项目根目录的配置。

| 配置 | 默认值 | 说明 |
|---|---|---|
| delete_after_export | false | 成功生成配对文件后是否删除远端缓存 |
| scan_interval | 2 | 扫描间隔（秒） |
| output_folder | DouyinLive | 输出目录，相对程序目录解析 |
| live_duration | 3.0 | 最多截取的秒数 |
| adb_path | 空字符串 | 自动寻找；可手动覆盖 |
| photo_format | heic | heic 或 jpeg |
| name_style | camera | camera 使用 IMG_0001；original 使用源文件名 |

## 命令行

以下命令在 EXE 所在目录执行：

```powershell
.\DouyinLiveExporter.exe --find-adb
.\DouyinLiveExporter.exe --convert ".\input.mp4"
.\DouyinLiveExporter.exe --convert ".\input.mp4" --cover ".\cover.jpg" --output ".\output"
.\DouyinLiveExporter.exe --convert ".\input.mp4" --photo-format jpeg --name-style original
.\DouyinLiveExporter.exe --verify ".\IMG_0001.HEIC" ".\IMG_0001.MOV"
```

## 开发与构建

要求 Windows、Python 3.11 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r build\requirements.txt
.\.venv\Scripts\python.exe src\DouyinLiveExporter.py
.\build\build.bat
```

构建输出位于 `dist/AppleLivePhoto_v4/`，包含 EXE、默认配置及文档。运行 EXE 不需要另装 Python 或 FFmpeg；ADB 使用 MuMu 自带版本。

开发者检查：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`src/` 为源码，`tests/` 为合成素材的自动化检查，`build/` 中仅构建脚本和依赖清单纳入版本管理。`dist/`、虚拟环境、个人素材及本地诊断文件均不上传。

## 许可证与第三方依赖

项目源码使用 MIT 许可证。Pillow、pillow-heif/libheif、imageio-ffmpeg/FFmpeg 和 PyInstaller 各自适用其许可证；分发包含这些组件的二进制时，应同时遵守对应许可证及源码提供要求。仓库不包含 MuMu/ADB 二进制和个人照片。

## 格式参考

- [Apple：保存 Live Photos](https://developer.apple.com/documentation/avfoundation/capturing-and-saving-live-photos)
- [Apple：配对标识](https://developer.apple.com/documentation/avfoundation/avcapturephotosettings/livephotomoviemetadata)
- [Apple：QuickTime 元数据键表](https://developer.apple.com/documentation/quicktime-file-format/metadata_key_table_atom)
- [ExifTool：Apple MakerNote](https://exiftool.org/TagNames/Apple.html)
