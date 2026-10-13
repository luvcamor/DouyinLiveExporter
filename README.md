# DouyinLiveExporter

Windows 下的抖音评论实况图导出工具。从已开启 Root ADB 的 MuMu 模拟器读取新保存的缓存，生成苹果 Live Photo 配对资源；也支持转换本地 MP4/MOV。

## 功能

- 自动寻找 MuMu 安装目录中的 ADB，不限定安装盘符。
- 默认导出 HEIC（HEIF 容器）+ MOV，可选 JPG + MOV。
- 写入照片 Apple MakerNote、MOV 电影级配对标识及静态帧时间轨道。
- 使用 IMG_0001 等短文件名，每次导出放在独立目录。
- 保留原始缓存，转换失败不删除模拟器文件。
- 校验配对元数据及视频解码。

当前支持苹果配对格式；尚未实现安卓 Motion Photo。

## 使用前需要准备什么

**首次使用不能只打开模拟器就运行：还需要在 MuMu 中开启 ADB 调试和 Root，并在模拟器内安装抖音。完成一次配置后，日常使用才是「启动模拟器 → 运行程序 → 开始监听 → 在抖音保存实况图」。**

| 使用方式 | 必要条件 |
|---|---|
| 从抖音评论区自动导出（菜单 1） | Windows、已启动的 MuMu 安卓实例、ADB 本地连接、可用的 Root ADB、模拟器内的抖音 |
| 转换已有 MP4/MOV（菜单 4） | Windows 和本地视频；不需要 MuMu、ADB、Root 或抖音 |
| 运行已构建的 EXE | 无需另装 Python 或 FFmpeg；使用可写入的程序目录 |
| 直接运行 Python 源码 | Python 3.11+，先安装 `build/requirements.txt` 中的依赖 |

GitHub 源码仓库不包含 EXE。下载源码 ZIP 后，需要按下方「开发与构建」安装依赖并运行源码，或自行构建 EXE。当前构建目录仍名为 `AppleLivePhoto_v4`，这是历史内部命名，不影响仓库 v1 版本使用。

### 首次配置 MuMu

1. 安装 MuMu，启动一个安卓实例，等待进入安卓桌面。只打开多开器列表、没有启动安卓实例不够。建议先只运行一个实例，程序目前没有设备选择菜单。
2. 在 MuMu 设置中找到 **ADB 调试**，开启允许本地连接的选项；再开启 **Root 权限／手机 Root**。不同版本入口名称和位置可能不同，以所用版本界面为准；如提示重启，请重启安卓实例。
3. 在模拟器里安装并打开**抖音普通版**（包名 `com.ss.android.ugc.aweme`），根据抖音要求登录，确保能查看评论区实况图并长按保存。TikTok、抖音极速版、网页版和手机上的抖音不属于当前监听目标。
4. 若抖音请求保存图片所需权限，请允许。若 MuMu 弹出 Root 授权提示，请允许。本程序需要读取抖音私有缓存目录，普通 ADB 权限不够。

程序会自动执行 `adb root`，并以 `adb shell id` 返回 `uid=0(root)` 为通过条件。仅在模拟器中能使用 `su`，不代表当前脚本的 Root ADB 检查能通过。Windows「以管理员身份运行」也不能替代模拟器 Root 权限。

ADB 端口位置可参考 [MuMu 官方 ADB 连接说明](https://mumu.163.com/help/20240807/40912_1073151.html)。当前程序自动尝试本机 `127.0.0.1:16384` 至 `16390`，不会自动扫描所有实例端口；自动找到 ADB 文件不等于兼容所有 MuMu 版本和端口。

### 每次从模拟器导出的正确顺序

1. **先启动 MuMu 安卓实例**，确认抖音可以正常打开。
2. 运行程序：双击构建后的 `dist/AppleLivePhoto_v4/DouyinLiveExporter.exe`；源码运行方式见下方。
3. 输入 **1** 并回车。程序会寻找 ADB、连接模拟器、尝试 Root，然后列出已有缓存。
4. **等窗口显示「忽略已有文件: …」和「监听中...」后，再到模拟器内操作。**
5. 在抖音中打开评论区的 **Live／实况图片**，等待内容加载，然后长按并保存。仅浏览图片、保存普通静态图片或在真实手机上保存，不会完成这条导出流程。
6. 等待控制台显示「苹果 Live Photo 已生成并通过文件验证」，再查看输出目录。转换期间不要关闭程序和模拟器。
7. 将同一目录内的 HEIC/JPG 和 MOV 配对导入 iPhone，具体方法见下文。

EXE 的输出在 **EXE 旁的 `DouyinLive/AppleLive`**；源码运行时输出在 **项目根目录的 `DouyinLive/AppleLive`**。程序只在检测到新文件并成功转换后生成结果，不是启动后立即生成。

**启动监听时已有的缓存会被忽略。** 必须先开始监听，再保存目标实况图；如果抖音复用了旧缓存文件名，再次保存同一张图也可能不触发。可以先换一张未保存过的实况图确认流程。菜单 **2** 会删除监听目录内的历史缓存，不是单纯刷新列表；确需清理时，先停止监听、确认需要的文件已备份，再执行清理并重新开始监听。

### 只转换以前导出的 MP4/MOV

运行程序，选择 **4**，输入视频路径（可把视频拖进控制台窗口）并回车即可。这个模式无需启动模拟器。它会生成实况照片资源，但不会自动发送到手机，也不会直接写入 iPhone 相册。

### 常见问题

| 现象 | 应检查的内容 |
|---|---|
| 未找到可用的 MuMu ADB | 确认 MuMu 已安装；启动实例后重试。用 `--find-adb` 查看定位结果，特殊安装环境可填写 `adb_path` |
| 已显示 ADB 路径，但提示未找到 MuMu | 检查安卓实例是否启动、ADB 本地连接是否开启、实例端口是否在自动尝试范围内 |
| 实例使用其他端口 | 可使用找到的 ADB 手动执行 `adb connect 127.0.0.1:实际端口` 后重试；此处 `adb` 应替换为实际 ADB 可执行文件路径。程序可选择已连接的 `127.0.0.1` 设备 |
| Root ADB 失败 | 开启模拟器 Root、处理授权弹窗并按要求重启；该实例需要支持 `adb root` |
| 读取缓存目录失败／目录不存在 | 确认是抖音普通版且已使用评论图片功能。若目录尚未生成，可先保存一张图片初始化，再重新监听并保存另一张；抖音版本变更也可能改变缓存位置 |
| 一直监听却没有输出 | 确认在监听开始后保存了新的评论实况图，而不是只打开预览或复用旧缓存 |
| 缓存不是 MP4/MOV／转换失败 | 保留报错与原文件；当前仅处理实际视频容器，不支持所有版本的混合缓存格式 |
| 手机中出现照片和视频两个文件 | 需要支持 Live Photo 配对导入的方式，普通文件传输不会保证自动合并 |

程序当前读取 `/data/data/com.ss.android.ugc.aweme/files/comment/images` 中以 `image_` 开头的新文件。MuMu 或抖音升级可能影响权限、端口或缓存结构；自动发现 ADB 不等于对所有版本都已验证。

监听时按 Ctrl+C 返回菜单；选择 **3** 退出。

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
