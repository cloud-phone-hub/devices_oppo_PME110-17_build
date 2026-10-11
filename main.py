#!/usr/bin/env python3
"""PME110-17（OPPO Find X9s Pro，MediaTek / ColorOS V17.0.0 / Android 17）构建全流程编排（main）。

按顺序串联 build/scripts/ 下的 python 脚本（与 buildenv.STAGES 一致）：

  unpack       -> unpack-roms.py       解 OPPO A/B 全量 OTA（payload.bin）为各分区镜像

后续阶段（待外部输入就位后逐步补齐，见 README/汇报）：
  kernel / boot / vendor_boot / vendor / vendor_dlkm / super / pack

用法（可在任何目录）：
  python3 build/main.py                    # 全流程（当前仅 unpack）
  python3 build/main.py --only unpack      # 只跑指定阶段
  python3 build/main.py --dry-run          # 只打印将执行的命令
  python3 build/main.py --device-info      # 只打印机型 TSV 行（供 just device list）
  python3 build/main.py --build-id ID      # 选择 manifest.json 固件条目（导出 CDH_*）
"""

import argparse
import json
import os
import subprocess
import sys

BUILD_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(BUILD_DIR, "scripts")

_manifest_path = os.path.join(BUILD_DIR, "manifest.json")


def _load_manifest():
    """读取 manifest.json（声明 roms/ 下支持的固件与关键镜像），返回 dict。"""
    try:
        with open(_manifest_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _print_device_info(manifest):
    if not manifest:
        print("[warn] 缺少或无法解析 manifest.json，跳过设备信息")
        return
    dev = manifest.get("device", {})
    builds = manifest.get("build", [])
    print(f"  设备: {dev.get('name') or dev.get('codename') or '未知'}")
    ids = [b.get("build-id") for b in builds if b.get("build-id")]
    if ids:
        print(f"  可编译 build-id: {', '.join(ids)}")


def _device_info_lines(manifest):
    """机型 TSV 行（供 just device list 收集），每个 build-id 一行：
    <vendor>/<device>\\t<显示名>\\t<build-id>
    """
    dev = manifest.get("device", {}) if manifest else {}
    builds = manifest.get("build", []) if manifest else []
    name = dev.get("name") or dev.get("codename") or "unknown"
    vendor = os.path.basename(os.path.dirname(os.path.dirname(BUILD_DIR)))
    device = os.path.basename(os.path.dirname(BUILD_DIR))
    ids = [b.get("build-id") for b in builds if b.get("build-id")] or [""]
    return [f"{vendor}/{device}\t{name}\t{i}" for i in ids]


def _select_build(manifest, build_id):
    """按 --build-id 选择 manifest build 条目，返回 (entry, err)。"""
    builds = (manifest or {}).get("build", [])
    if build_id:
        for b in builds:
            if b.get("build-id") == build_id:
                return b, None
        ids = [b.get("build-id") for b in builds]
        return None, f"未知 build-id: {build_id}（可选: {', '.join(ids)}）"
    if len(builds) == 1:
        return builds[0], None
    return None, None


def _export_build_env(entry):
    """把选中 build 条目导出为 CDH_* 环境变量（各阶段脚本单一数据源）。"""
    build_id = entry.get("build-id", "")
    dev_root = os.path.dirname(BUILD_DIR)
    roms = os.path.join(dev_root, "roms")
    lineage_rom = os.path.abspath(os.path.join(dev_root, "..", "..", "..", "lineage-rom"))
    pairs = {
        "CDH_BUILD_ID": build_id,
        "CDH_VERSION": entry.get("version", ""),
        "CDH_FACTORY_ZIP": (
            os.path.join(roms, entry["factory-zip"]) if entry.get("factory-zip") else ""),
        "CDH_FACTORY_DIR": (
            os.path.join(roms, entry["factory-dir"]) if entry.get("factory-dir") else ""),
        "CDH_LINEAGE_ZIP": (
            os.path.join(lineage_rom, entry["lineage-zip"]) if entry.get("lineage-zip") else ""),
        "CDH_LINEAGE_DIR": (
            os.path.join(lineage_rom, entry["lineage-dir"]) if entry.get("lineage-dir") else ""),
        "CDH_BASELINES_JSON": (
            os.path.join(BUILD_DIR, "baselines", f"{build_id}.json") if build_id else ""),
    }
    for k, v in pairs.items():
        if v:
            os.environ[k] = v
            print(f"  {k}={v}")


# 阶段：短名 -> (脚本文件名, 追加参数)
STAGE_SCRIPTS = [
    ("unpack", "unpack-roms.py", []),
]
STAGE_NAMES = [s[0] for s in STAGE_SCRIPTS]


def _stage_index(name):
    try:
        return STAGE_NAMES.index(name)
    except ValueError:
        print(f"[err] 未知阶段: {name}（可选: {', '.join(STAGE_NAMES)}）")
        sys.exit(2)


def _run_script(script, extra, dry_run):
    path = os.path.join(SCRIPTS_DIR, script)
    cmd = [sys.executable, path] + extra
    print("  + " + " ".join(cmd))
    if dry_run:
        return 0
    rc = subprocess.run(cmd)
    if rc.returncode != 0:
        print(f"[err] {script} 执行失败 (rc={rc.returncode})")
        sys.exit(rc.returncode)
    return 0


def main():
    ap = argparse.ArgumentParser(description="PME110-17 构建全流程编排")
    ap.add_argument("--skip-unpack", action="store_true", help="跳过 unpack（已解好时）")
    ap.add_argument("--only", metavar="STAGE", help=f"只跑指定阶段（{', '.join(STAGE_NAMES)}）")
    ap.add_argument("--from", dest="from_stage", metavar="STAGE", help="从指定阶段起跑（含）")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的命令")
    ap.add_argument("--device-info", action="store_true",
                    help="只打印机型 TSV 行（vendor/device、显示名、build-id）后退出")
    ap.add_argument("--build-id", metavar="ID",
                    help="选择 manifest.json 中的固件条目，并导出 CDH_* 环境变量驱动各阶段")
    args = ap.parse_args()

    if args.device_info:
        for line in _device_info_lines(_load_manifest()):
            print(line)
        return 0

    manifest = _load_manifest()
    entry, err = _select_build(manifest, args.build_id)
    if err:
        print(f"[err] {err}")
        sys.exit(2)
    if entry:
        bid = entry.get("build-id", "")
        print(f"==> 选择固件 build-id: {bid}"
              + ("" if args.build_id else "（自动选中唯一条目）"))
        _export_build_env(entry)
    else:
        print("[warn] manifest.json 无 build 条目（或多条目未指定 --build-id），"
              "各阶段使用内置默认固件")

    _print_device_info(manifest)

    stages = list(STAGE_SCRIPTS)
    if args.skip_unpack:
        stages = [s for s in stages if s[0] != "unpack"]
    if args.only:
        _stage_index(args.only)
        stages = [s for s in stages if s[0] == args.only]
        if not stages:
            print(f"[err] 阶段 {args.only} 已被 --skip-unpack 移除")
            sys.exit(2)
    elif args.from_stage:
        _stage_index(args.from_stage)
        names = [s[0] for s in stages]
        if args.from_stage not in names:
            print(f"[err] 阶段 {args.from_stage} 已被 --skip-unpack 移除")
            sys.exit(2)
        stages = stages[names.index(args.from_stage):]

    if not stages:
        print("[err] 没有要执行的阶段")
        sys.exit(2)

    print(f"==> 执行 {len(stages)} 个阶段: {', '.join(n for n, _, _ in stages)}")
    for name, script, extra in stages:
        print(f"==> [{name}] {script}")
        _run_script(script, extra, args.dry_run)
    print("[ok] 全流程完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())