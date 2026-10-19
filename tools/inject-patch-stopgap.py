#!/usr/bin/env python3
"""临时（stopgap）：把 build/vendor/patch 注入替位 vendor.img，供「测试启动」用。

正式路径是 build-vendor.py（需 baselines 的 SELinux 标签清单）；本脚本在 baselines
就位前把契约件（fstab.mt6993 / init.mt6993.rc / init.virt.rc / cph_*.rc / bin/* 等）
用固定标签注入，让客机二阶段能读到 /vendor/etc/fstab.<hw> 与 init.<hw>.rc。
标签规则照 oriole-16 baselines 的 vendor.selinux-labels 映射。

用法：python3 build/tools/inject-patch-stopgap.py [--dry-run]
"""
import argparse
import os
import subprocess
import sys

BUILD_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # <dev>/build
DEV_ROOT = os.path.dirname(BUILD_DIR)
PATCH_TREE = os.path.join(BUILD_DIR, "vendor", "patch")
VENDOR_IMG = os.path.join(DEV_ROOT, "out", "dist", "rom", "vendor.img")
DEBUGFS = os.environ.get("CDH_DEBUGFS", "/opt/homebrew/opt/e2fsprogs/sbin/debugfs")

# 与 oriole-16 baselines 的 vendor.selinux-labels 同口径（键=注入树相对路径）
LABELS = {
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
    "usr/idc/QEMU Virtio Tablet.idc": "u:object_r:vendor_file:s0",
    "usr/idc/virt_tablet2multitouch.idc": "u:object_r:vendor_file:s0",
}
EXEC = {"bin/netmgr_setup"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(VENDOR_IMG):
        print(f"[err] 缺 {VENDOR_IMG}")
        return 1

    cmds = []
    n = 0
    for root, _dirs, files in os.walk(PATCH_TREE):
        rel_dir = os.path.relpath(root, PATCH_TREE)
        img_dir = "/" if rel_dir == "." else "/" + rel_dir.replace(os.sep, "/")
        cmds.append(f"mkdir {img_dir}")
        for name in sorted(files):
            rel = os.path.relpath(os.path.join(root, name), PATCH_TREE).replace(os.sep, "/")
            if " " in rel:  # debugfs write 的宿主侧空格坑（见 buildenv 记录）
                print(f"[skip] 含空格路径: {rel}")
                continue
            label = LABELS.get(rel)
            if not label:
                print(f"[skip] 未登记标签: {rel}")
                continue
            mode = "0x81ed" if rel in EXEC else "0x81a4"
            img = img_dir + "/" + name
            cmds += [f"rm {img}", f"write {os.path.join(root, name)} {img}",
                     f"sif {img} mode {mode}", f"sif {img} uid 0", f"sif {img} gid 0",
                     f"ea_set {img} security.selinux {label}"]
            n += 1

    print(f"[..] 注入 {n} 个文件 -> {VENDOR_IMG}")
    if args.dry_run:
        print("\n".join(cmds))
        return 0
    cmd_file = os.path.join(DEV_ROOT, "out", "tmp", "inject-stopgap.cmd")
    os.makedirs(os.path.dirname(cmd_file), exist_ok=True)
    with open(cmd_file, "w") as f:
        f.write("\n".join(cmds) + "\n")
    res = subprocess.run([DEBUGFS, "-w", "-f", cmd_file, VENDOR_IMG],
                         capture_output=True, text=True)
    out = res.stdout + res.stderr
    bad = [l for l in out.splitlines() if "error" in l.lower() or "Usage" in l]
    if bad:
        print("\n".join(bad[:20]))
        return 1
    print(f"[ok] 注入完成（{n} 文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())