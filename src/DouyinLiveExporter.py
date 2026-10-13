# -*- coding: utf-8 -*-
import subprocess
import time
import json
import sys
import argparse
import hashlib
import math
import shlex
from pathlib import Path

from live_photo import ConversionError, convert_live_photo, verify_live_photo
from adb_discovery import discover_adb

BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent.parent
CONFIG_FILE = BASE / "config.json"

if not CONFIG_FILE.exists():
    CONFIG_FILE.write_text(json.dumps({
        "delete_after_export": False,
        "scan_interval": 2,
        "output_folder": "DouyinLive"
    }, indent=4), encoding="utf-8")

CONFIG = json.loads(CONFIG_FILE.read_text("utf-8"))

REMOTE_DIR = "/data/data/com.ss.android.ugc.aweme/files/comment/images"
OUTPUT_DIR = BASE / CONFIG.get("output_folder", "DouyinLive")

adb_path = None
device = None


def adb(*args):
    cmd = [adb_path]
    if device:
        cmd += ["-s", device]
    return subprocess.run(cmd + list(args), capture_output=True, text=True, encoding="utf-8", errors="ignore")


def init():
    global adb_path, device
    adb_path, device = None, None
    print("正在自动寻找 MuMu ADB...")
    adb_path = discover_adb(BASE, CONFIG.get('adb_path', ''))
    if not adb_path:
        print("未找到可用的 MuMu ADB，请先启动模拟器再试。也可将 adb 放到程序目录，或设置 adb_path。")
        return False
    print("使用 ADB:", adb_path)
    for port in range(16384, 16391):
        subprocess.run([adb_path, "connect", f"127.0.0.1:{port}"], capture_output=True)
    r = subprocess.run([adb_path, "devices"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if "127.0.0.1:" in line and "\tdevice" in line:
            device = line.split("\t")[0]
            return True
    return False


def root():
    adb("root")
    for _ in range(10):
        time.sleep(1)
        if "uid=0(root)" in adb("shell", "id").stdout:
            return True
    return False


def files():
    r = adb("shell", "ls", "-1", REMOTE_DIR)
    if r.returncode:
        raise RuntimeError("读取缓存目录失败: " + r.stderr.strip())
    return {x.strip() for x in r.stdout.splitlines()
            if x.startswith("image_") and "/" not in x and "\\" not in x}


def cleanup():
    old = files()
    print("历史 Live:", len(old))
    for item in old:
        adb("shell", "rm", "--", shlex.quote(f"{REMOTE_DIR}/{item}"))
        print("已删除:", item)


def stable(name):
    last = -1
    for _ in range(5):
        r = adb("shell", "stat", "-c", "%s", shlex.quote(f"{REMOTE_DIR}/{name}"))
        try:
            size = int(r.stdout.strip())
        except ValueError:
            size = 0
        if size > 0 and size == last:
            return True
        last = size
        time.sleep(1)
    return False


def export_file(name):
    originals = OUTPUT_DIR / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    # The remote name identifies only the in-progress transfer. Finished raw
    # backups are content-addressed so reused remote names cannot replace them.
    target = originals / (hashlib.sha256(name.encode()).hexdigest()[:24] + ".bin")
    partial = target.with_suffix(".part")
    print("发现新 Live:", name)
    try:
        result = adb("pull", f"{REMOTE_DIR}/{name}", str(partial))
        if result.returncode or not partial.exists() or partial.stat().st_size == 0:
            print("拉取失败，未生成 Live Photo:", result.stderr.strip())
            return False
        with partial.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        target = originals / (digest + '.bin')
        if target.exists():
            partial.unlink()
        else:
            partial.rename(target)
        pair = convert_live_photo(target, OUTPUT_DIR / "AppleLive",
                                  max_duration=float(CONFIG.get("live_duration", 3.0)),
                                  photo_format=CONFIG.get('photo_format', 'heic'),
                                  name_style=CONFIG.get('name_style', 'camera'))
        print("苹果 Live Photo 已生成并通过文件验证:", Path(pair["photo"]).parent)
        print("请按目录中的导入说明，将 HEIC/JPG 和 MOV 作为一张 Live Photo 导入。")
        if CONFIG.get("delete_after_export", False):
            removed = adb("shell", "rm", "--", shlex.quote(f"{REMOTE_DIR}/{name}"))
            if removed.returncode:
                print("Live Photo 已保存，但远端缓存未删除:", removed.stderr.strip())
        return True
    except (ConversionError, OSError, ValueError) as exc:
        print("Live Photo 转换失败:", exc)
        print("保留模拟器缓存和已拉取的原始文件:", target)
        return False
    finally:
        partial.unlink(missing_ok=True)


def listen():
    baseline = files()
    retry_after = {}
    print("忽略已有文件:", len(baseline))
    print("监听中...")
    while True:
        for item in files() - baseline:
            if time.monotonic() < retry_after.get(item, 0):
                continue
            if stable(item) and export_file(item):
                baseline.add(item)
                retry_after.pop(item, None)
            else:
                retry_after[item] = time.monotonic() + 60
        time.sleep(CONFIG.get("scan_interval", 2))


def _positive_seconds(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("时长必须为正数")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description="抖音缓存 / 本地视频转苹果 Live Photo")
    parser.add_argument('--version', action='version', version='DouyinLiveExporter Apple-v4-AutoADB')
    parser.add_argument('--find-adb', action='store_true', help='显示自动找到的 ADB 路径，不连接或修改模拟器')
    parser.add_argument('--photo-format', choices=['heic', 'jpeg'], default=CONFIG.get('photo_format', 'heic'))
    parser.add_argument('--name-style', choices=['camera', 'original'], default=CONFIG.get('name_style', 'camera'))
    parser.add_argument("--convert", type=Path, help="转换已有 MP4/MOV，不需要模拟器")
    parser.add_argument("--cover", type=Path, help="可选原始封面；默认提取视频中间帧")
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR / "AppleLive")
    parser.add_argument("--duration", type=_positive_seconds,
                        default=str(CONFIG.get("live_duration", 3.0)), help="取开头最多几秒，默认 3")
    parser.add_argument("--verify", nargs=2, type=Path, metavar=("PHOTO", "MOV"))
    args = parser.parse_args(argv)
    if args.find_adb:
        found = discover_adb(BASE, CONFIG.get('adb_path', ''))
        print(found or '未找到 MuMu ADB')
        return 0 if found else 1
    try:
        if args.verify:
            print(json.dumps(verify_live_photo(*args.verify), ensure_ascii=False, indent=2))
            return 0
        if args.convert:
            pair = convert_live_photo(args.convert, args.output, cover=args.cover, max_duration=args.duration,
                                      photo_format=args.photo_format, name_style=args.name_style)
            print("苹果 Live Photo 已生成:", Path(pair["photo"]).parent)
            return 0
    except (ConversionError, OSError, ValueError) as exc:
        print("操作失败:", exc)
        return 1
    while True:
        print("\nDouyinLiveExporter Apple-v4（HEIC + MOV / 自动寻找 MuMu ADB）")
        print("\n1. 监听并导出苹果 Live Photo\n2. 清理模拟器历史缓存\n3. 退出\n4. 转换已有 MP4/MOV")
        choice = input("选择: ")
        try:
            if choice in ("1", "2"):
                if not init():
                    print("未找到 MuMu")
                    continue
                if not root():
                    print("Root ADB失败")
                    continue
                if choice == "1":
                    listen()
                else:
                    cleanup()
            elif choice == "3":
                return 0
            elif choice == "4":
                source = Path(input("视频路径（可将文件拖入窗口）: ").strip().strip('"'))
                pair = convert_live_photo(source, args.output, max_duration=args.duration,
                                          photo_format=args.photo_format, name_style=args.name_style)
                print("苹果 Live Photo 已生成:", Path(pair["photo"]).parent)
        except KeyboardInterrupt:
            print("\n已停止监听，返回菜单。")
        except (RuntimeError, OSError, ValueError) as exc:
            print("操作失败:", exc)


if __name__ == "__main__":
    sys.exit(main())
