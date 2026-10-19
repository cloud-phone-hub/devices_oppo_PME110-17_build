#!/usr/bin/env python3
"""生成 build/baselines/<build-id>.json（PME110-17）。

三块数据：
  vendor.build-prop-sets / build-prop-unsets
      取自**官方 vendo  r.img /build.prop**（OPPO 官方件是 erofs，走 dump.erofs --cat），
      按 oriole-16 的口径过滤：剔除图形栈选择/调优键与 trusty HAL 选择键（云机图形栈是
      mesa + virtio_gpu + minigbm，必须由 build.prop 指定而非等 rc setprop），并锁
      64-only（HVF 客机无 AArch32）。
  vendor.selinux-labels
      注入树（build/vendor/patch + out/dist/vendor）内每个文件的 security.selinux 标签，
      键 = 相对路径。规则照 oriole-16 的清单（同为 note13 派生注入树）。
  vendor-dlkm.baseline-build-prop
      官方 vendor_dlkm.img 的 /etc/build.prop（OPPO 官方件为 erofs）→ length+sha256+label。

用法：
  python3 build/tools/gen-baselines.py            # 生成/覆盖
  python3 build/tools/gen-baselines.py --dry-run  # 只打印
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

BUILD_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BUILD_DIR, "scripts"))

from buildenv import BUILD_ID, ROM_ROOT_DIR, load_baselines  # noqa: E402
from buildenv import any_tool  # noqa: E402

PATCH_TREE = os.path.join(BUILD_DIR, "vendor", "patch")
BASELINES = os.path.join(BUILD_DIR, "baselines", f"{BUILD_ID}.json")
VENDOR_IMG = os.path.join(ROM_ROOT_DIR, "vendor.img")
VENDOR_DLKM_IMG = os.path.join(ROM_ROOT_DIR, "vendor_dlkm.img")

# 注入树标签规则（键 = 注入树内相对路径）。照 oriole-16 的同名清单。
LABEL_RULES = {
    "bin/logcat-dump": "u:object_r:system_file:s0",
    "bin/setup_display.sh": "u:object_r:system_file:s0",
    "bin/netmgr_setup": "u:object_r:pioneer_exec:s0",
    "etc/fstab.mt6993": "u:object_r:vendor_configs_file:s0",
    "etc/init/cph_daemon.rc": "u:object_r:system_file:s0",
    "etc/init/cph_disable_provision.rc": "u:object_r:vendor_file:s0",
    "etc/init/cph_logcat_dump.rc": "u:object_r:vendor_file:s0",
    "etc/init/cph_start_adbd.rc": "u:object_r:vendor_file:s0",
    "etc/init/netmgr.rc": "u:object_r:vendor_file:s0",
    "etc/init/cdh_media32.rc": "u:object_r:vendor_configs_file:s0",
    "etc/init/hw/init.mt6993.rc": "u:object_r:vendor_configs_file:s0",
    "etc/init/hw/init.virt.rc": "u:object_r:vendor_configs_file:s0",
    "etc/permissions/android.hardware.telephony.xml": "u:object_r:vendor_configs_file:s0",
    "etc/permissions/privapp-permissions-miuihome.xml": "u:object_r:vendor_configs_file:s0",
    "usr/idc/QEMU Virtio MultiTouch.idc": "u:object_r:vendor_file:s0",
    "usr/idc/QEMU Virtio Tablet.idc": "u:object_r:vendor_file:s0",
    "usr/idc/virt_tablet2multitouch.idc": "u:object_r:vendor_file:s0",
    # out/dist/vendor 侧（source 子构建产物；daemon 自身不登记，手工补）
    "bin/daemon": "u:object_r:pioneer_exec:s0",
    "bin/hw/android.hardware.wifi-service.cdh-note13": "u:object_r:hal_wifi_default_exec:s0",
    "etc/init/android.hardware.wifi-service.cdh-note13.rc": "u:object_r:vendor_configs_file:s0",
    "etc/vintf/manifest/android.hardware.wifi-service.xml": "u:object_r:vendor_configs_file:s0",
}

# 必须由云机 build.prop 指定的图形栈选择键（不能等 rc 的 setprop：ro.* 是 set-once，
# build.prop 在 init property_init 阶段加载，早于 virtgpu_detect / init.virt.rc 触发）
FORCED_SETS = [
    ["ro.hardware.egl", "mesa"],
    ["ro.hardware.vulkan", "virtio"],
    ["ro.hardware.gralloc", "minigbm"],
]

# 官方件里必须剔除的键（前缀/精确匹配）：图形栈选择与调优、trusty HAL 选择、32 位口径
DROP_EXACT = {
    "ro.opengles.version", "ro.hwui.use_vulkan", "graphics.gpu.profiler.support",
    "ro.hardware.keystore", "ro.hardware.gatekeeper",
    "ro.zygote", "ro.vendor.product.cpu.abilist32",
}
DROP_PREFIX = (
    "ro.egl.", "ro.hardware.egl", "ro.hardware.vulkan", "vendor.mali.", "debug.mali.",
    "debug.sf.", "debug.hwui.", "ro.bionic.2nd_", "dalvik.vm.isa.arm.",
    "ro.hardware.egl.", "ro.hwui.",
)
# 64-only 口径（HVF 客机无 AArch32；同 popsicle/oriole）
FORCED_64BIT = [
    ["ro.zygote", "zygote64"],
    ["ro.vendor.product.cpu.abilist32", ""],
]


# out/dist/vendor 侧（source 子构建产物）的条目：**无条件登记**，不依赖构建先后
# （生成 baselines 时 staging 树可能尚未存在；wifi 子构建另会自行登记同一批键）。
STAGING_KEYS = (
    "bin/daemon",
    "bin/hw/android.hardware.wifi-service.cdh-note13",
    "etc/init/android.hardware.wifi-service.cdh-note13.rc",
    "etc/vintf/manifest/android.hardware.wifi-service.xml",
)


def _erofs_cat(img, inner):
    dumper = any_tool(["dump.erofs"], ("/opt/homebrew/bin", "/usr/local/bin"))
    if not dumper:
        raise FileNotFoundError("缺少 dump.erofs（brew install erofs-utils）")
    res = subprocess.run([dumper, "--cat", f"--path={inner}", img],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0 or b"failed to lookup" in res.stdout + res.stderr:
        raise SystemExit(f"[err] 读取失败: {img}:{inner}\n"
                         f"{res.stdout[:200]!r} {res.stderr[:200]!r}")
    return res.stdout


def build_prop_sets():
    """官方 vendor.img /build.prop -> (sets, unsets)，按云机口径过滤。"""
    text = _erofs_cat(VENDOR_IMG, "/build.prop").decode("utf-8", "replace")
    sets, dropped = [], []

    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        k = k.strip()
        if k in DROP_EXACT or k.startswith(DROP_PREFIX):
            dropped.append(k)
            continue
        # 同键多次出现时**后者胜**（build.prop 语义；如 OPPO 先写
        # ro.board.platform=common 再写 =mt6993，取后者）
        sets = [e for e in sets if e[0] != k]
        sets.append([k, v])
    for k, v in FORCED_SETS + FORCED_64BIT:
        for e in sets:
            if e[0] == k:
                e[1] = v
                break
        else:
            sets.append([k, v])
    print(f"[ok] build-prop-sets: {len(sets)} 条（官方剔除 {len(dropped)} 条）")
    print(f"     剔除样例: {sorted(set(dropped))[:10]}")
    return sets, []


def selinux_labels():
    """注入树（patch + out/dist/vendor）标签表：按实际文件生成，未知文件报错。"""
    labels = {k: LABEL_RULES[k] for k in STAGING_KEYS}
    unknown = []
    for tree in (PATCH_TREE, os.path.join(BUILD_DIR, "..", "out", "dist", "vendor")):
        if not os.path.isdir(tree):
            continue
        for root, _dirs, files in os.walk(tree):
            for name in files:
                if name == ".DS_Store":
                    continue
                rel = os.path.relpath(os.path.join(root, name), tree).replace(os.sep, "/")
                lab = LABEL_RULES.get(rel)
                if not lab:
                    unknown.append(rel)
                    continue
                labels[rel] = lab
    if unknown:
        print(f"[warn] 注入树内有未登记标签的文件（子构建会自行登记，此处跳过）: {sorted(unknown)}")
    print(f"[ok] selinux-labels: {len(labels)} 条")
    return labels


def vendor_dlkm_baseline():
    """官方 vendor_dlkm.img /etc/build.prop -> length/sha256/label。"""
    data = _erofs_cat(VENDOR_DLKM_IMG, "/etc/build.prop")
    e = {"path": "/etc/build.prop", "length": len(data),
         "sha256": hashlib.sha256(data).hexdigest(),
         "label": "u:object_r:vendor_configs_file:s0"}
    print(f"[ok] vendor-dlkm 基线件: {e['length']} B sha256={e['sha256'][:16]}…")
    return e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not BUILD_ID:
        raise SystemExit("[err] 无法确定 build-id（检查 manifest.json）")
    if not os.path.isfile(VENDOR_IMG):
        raise SystemExit(f"[err] 缺官方 vendor.img: {VENDOR_IMG}")

    sets, unsets = build_prop_sets()
    doc = {
        "schema": 1,
        "build-id": BUILD_ID,
        "comment": ("与 ROM 版本强相关的官方/基线清单（vendor 重打包的属性与注入件标签来源）。"
                    "build-prop-sets 逐条取自官方 vendor.img /build.prop（OPPO Find X9s Pro "
                    "PME110 / MT6993 / ColorOS V17.0.0，erofs 分区 dump.erofs 直读），"
                    "剔除图形栈选择/调优键与 trusty HAL 选择键，锁 64-only；"
                    "selinux-labels = 注入树 security.selinux 标签（键 = 注入树内相对路径）。"),
        "vendor": {
            "build-prop-sets": sets,
            "build-prop-unsets": unsets,
            "selinux-labels": selinux_labels(),
        },
        "vendor-dlkm": {
            "baseline-build-prop": vendor_dlkm_baseline(),
            "note": ("build-vendor_dlkm props 基线：官方 vendor_dlkm.img（OPPO 官方件，erofs）"
                     "内 /etc/build.prop，覆盖 lineage-23 基座渲染的 VirtIO 版本。"),
        },
    }
    if args.dry_run:
        print(json.dumps(doc, ensure_ascii=False, indent=1)[:1500])
        return 0
    os.makedirs(os.path.dirname(BASELINES), exist_ok=True)
    with open(BASELINES, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"[ok] 写入 {BASELINES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())