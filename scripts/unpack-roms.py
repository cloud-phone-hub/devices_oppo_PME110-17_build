#!/usr/bin/env python3
"""解包 PME110-17（OPPO Find X9s Pro）构建输入。

OPPO 官方固件为 A/B 全量 OTA zip（内含 payload.bin），分区**扁平分发**（无 AOSP
`super` 动态分区）。本脚本包装 payload-dumper-go（build/tools/dump_payload.py，
版本与 sha256 锁定），把各分区解出为独立镜像并**平铺**到 roms/<包名>/（输入分区源，
不落 out/），与 note13-5G-15 的 unpack 约定一致。

任务：
  payload   解出全部分区镜像到 roms/<包名>/（幂等：<name>.img 已存在则跳过）

用法（可在任何目录）：
  python3 build/scripts/unpack-roms.py                  # 等价 payload
  python3 build/scripts/unpack-roms.py payload
  python3 build/scripts/unpack-roms.py payload --list              # 只列分区清单
  python3 build/scripts/unpack-roms.py payload -p boot,vendor      # 只解指定分区
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
from buildenv import ROM_ROOT_DIR, ROM_ZIP, TOOLS_DIR  # noqa: E402

sys.path.insert(0, TOOLS_DIR)
import dump_payload  # noqa: E402


def _input_path():
    """优先用 OTA zip（payload-dumper-go 原地读，不落 8G payload）；否则用解压目录内 payload.bin。"""
    if ROM_ZIP and os.path.isfile(ROM_ZIP):
        return ROM_ZIP
    payload_bin = os.path.join(ROM_ROOT_DIR, "payload.bin") if ROM_ROOT_DIR else ""
    if payload_bin and os.path.isfile(payload_bin):
        return payload_bin
    raise SystemExit(
        "[err] 找不到固件：检查 roms/ 与 build/manifest.json 的 factory-zip/factory-dir")


def payload_task(only_list=False, partitions=(), jobs=0):
    """解 OTA payload 各分区到 roms/<包名>/，平铺为 <name>.img（幂等）。"""
    input_path = _input_path()
    out_dir = ROM_ROOT_DIR or dump_payload.default_out_dir(input_path)
    tool = dump_payload.ensure_tool()

    if only_list:
        dump_payload.list_partitions(tool, input_path)
        return 0

    known = dict(dump_payload.list_partitions(tool, input_path, quiet=True))
    targets = list(partitions) or list(known)
    unknown = [p for p in targets if p not in known]
    if unknown:
        raise SystemExit(f"[err] 分区不存在: {', '.join(unknown)}")

    todo = [p for p in targets
            if not os.path.isfile(os.path.join(out_dir, f"{p}.img"))]
    print(f"[plan ] 输出 {out_dir}")
    print(f"[plan ] 目标 {len(targets)} 个分区：已解 {len(targets) - len(todo)}，待解 {len(todo)}")
    if not todo:
        print("[done] 目标分区已全部就位（删掉对应 <name>.img 可重解）")
        return 0

    dump_payload.dump_partitions(tool, input_path, out_dir, todo, jobs, verify=True)
    print(f"[ok] 解出 {len(todo)} 个分区 -> {out_dir}")
    return 0


def main():
    argv = sys.argv[1:]
    only_list = "--list" in argv
    partitions, jobs = [], 0
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-p", "--partitions") and i + 1 < len(argv):
            partitions = [x.strip() for x in argv[i + 1].split(",") if x.strip()]
            i += 2
            continue
        if a == "--jobs" and i + 1 < len(argv):
            jobs = int(argv[i + 1])
            i += 2
            continue
        i += 1

    print("==> [payload]")
    return payload_task(only_list=only_list, partitions=partitions, jobs=jobs)


if __name__ == "__main__":
    sys.exit(main())