"""PME110-17（OPPO Find X9s Pro，MediaTek / ColorOS V17.0.0 / Android 17）构建环境。

各阶段脚本统一从这里读取构建选择与路径：env（CDH_*）优先，其次 build/manifest.json
推导；脚本不硬编码绝对路径。

与兄弟机型的差异（设备事实）：
  - 官方固件为 OPPO A/B 全量 OTA zip（内含 payload.bin），分区由 payload-dumper-go
    原地解出到 roms/<包名>/，平铺为 <name>.img；
  - 分区为**扁平分发**（无 AOSP `super` 动态分区），另含 ColorOS 专有 my_* 分区；
  - SoC 为 MediaTek（preloader_raw/lk/gz/sspm/scp/vcp 等），同族参考 note13-5G-15；
  - 引导/系统基线计划取 lineage virtio 虚机底包，Android 17 基线（lineage-24）待定。
"""

import json
import os

# 本文件位于 <设备>/build/scripts/ 下：向上 3 级为设备根，再向上 3 级为项目根
_DEV_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_DEV_ROOT)))

BUILD_DIR = os.path.join(_DEV_ROOT, "build")
ROMS_DIR = os.path.join(_DEV_ROOT, "roms")
OUT_DIR = os.path.join(_DEV_ROOT, "out")

# 抽取工具：payload-dumper-go（版本与 sha256 锁定见 build/tools/dump_payload.py）
TOOLS_DIR = os.path.join(BUILD_DIR, "tools")
DUMPER_BIN = os.path.join(TOOLS_DIR, "bin", "payload-dumper-go")


def env(name, default=""):
    """读取环境变量，未设置或为空时回退 default。"""
    return os.environ.get(name) or default


def _manifest():
    """读取 build/manifest.json（固件/构建声明），缺失或解析失败返回 {}。"""
    try:
        with open(os.path.join(BUILD_DIR, "manifest.json"), encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def _manifest_build():
    builds = (_manifest().get("build") or [])
    return builds[0] if builds else {}


_MB = _manifest_build()

# ---- 构建选择：CDH_BUILD_ID 优先，其次 manifest.json 首个 build ----
BUILD_ID = env("CDH_BUILD_ID", _MB.get("build-id") or "")

# Android 版本（主/主.次，取自 manifest build 的 android-version，如 17.0.0）
_ANDROID_VERSION = _MB.get("android-version") or ""
OS = _ANDROID_VERSION.split(".")[0] if _ANDROID_VERSION else "17"

# 固件版本号（用作 CDH_VERSION 与 pack 阶段输出目录名，如 17.0.0.102.cn01）
VERSION = env("CDH_VERSION", _MB.get("version") or "")

# ---- 官方固件输入（OPPO A/B OTA zip 与其解压目录）----
ROM_ZIP = env(
    "CDH_FACTORY_ZIP",
    os.path.join(ROMS_DIR, _MB["factory-zip"]) if _MB.get("factory-zip") else "")
ROM_ROOT_DIR = env(
    "CDH_FACTORY_DIR",
    os.path.join(ROMS_DIR, _MB["factory-dir"]) if _MB.get("factory-dir") else "")
# 解压目录内的 payload.bin（dump_payload 亦可直接读 zip）
ROM_PAYLOAD_BIN = os.path.join(ROM_ROOT_DIR, "payload.bin") if ROM_ROOT_DIR else ""

# ---- lineage 底包（虚机引导/系统基线；Android 17 基线待定）----
LINEAGE_ZIP = env("CDH_LINEAGE_ZIP", "")
if not LINEAGE_ZIP and _MB.get("lineage-zip"):
    _cand = os.path.join(PROJECT_ROOT, "lineage-rom", _MB["lineage-zip"])
    if os.path.isfile(_cand):
        LINEAGE_ZIP = _cand
LINEAGE_OUT_DIR = env(
    "CDH_LINEAGE_DIR",
    os.path.join(PROJECT_ROOT, "lineage-rom", _MB.get("lineage-dir") or "lineage-24"))

# ---- 输出布局 ----
# 最终盘集：项目级 out/device/<厂商>/<设备>/<OS>/<版本>/
VERSION_DIR = os.path.join(PROJECT_ROOT, "out", "device",
                           "oppo", "PME110-17", OS, VERSION.lower())
DIST_DIR = os.path.join(OUT_DIR, "dist")        # 分发镜像（boot/vendor/...）
ROM_DIST = os.path.join(DIST_DIR, "rom")
TMP_DIR = os.path.join(OUT_DIR, "tmp")          # 调试临时（不用 /tmp）
KERNEL_OUT = os.path.join(OUT_DIR, "kernel")    # 内核编译产物
KERNEL_SRC = os.path.join(_DEV_ROOT, "kernel", "source")  # 内核源码（待引入）

# ---- 构建阶段（后续阶段随脚本落地逐步补齐）----
STAGES = ["unpack"]