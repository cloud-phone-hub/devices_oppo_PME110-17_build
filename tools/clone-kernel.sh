#!/bin/bash
# PME110-17 内核源码准备：从共享 virtio 内核仓建 PME110-17 分支
#   lineage-23.2（基底） + cherry-pick oriole-16 的 CDH 基线提交
# 用法: bash devices/oppo/PME110-17/build/tools/clone-kernel.sh
set -euo pipefail

WS=/Users/cuimingqiang/workspace/cloud-phone-hub-ws
SRC="$WS/devices/oppo/PME110-17/kernel/source"
ORIOLE="$WS/devices/google/oriole-16/kernel/source"
REMOTE=git@github.com:cloud-phone-hub/android_kernel_virt_virtio.git
export GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=20"

if [[ -d "$SRC/.git" ]]; then
  echo "[skip] 已存在: $SRC"
  exit 0
fi

mkdir -p "$(dirname "$SRC")"
echo ">>> clone --depth 1 --branch lineage-23.2"
git clone --depth 1 --branch lineage-23.2 "$REMOTE" "$SRC"

cd "$SRC"
BASE=$(git rev-parse HEAD)
echo ">>> base(lineage-23.2) = $BASE"

echo ">>> fetch oriole-16 分支（本地路径，含 CDH 基线提交链）"
git remote add oriole "$ORIOLE"
git fetch oriole oriole-16

echo ">>> 建 PME110-17 分支并 cherry-pick CDH 提交"
git checkout -b PME110-17 "$BASE"
# oriole-16 = lineage-23.2 + 4 个 CDH 提交（基座建立 / popsicle 基线合入 / wifi BH 修 / media rc 重定向）
git log --oneline --reverse "$BASE"..oriole-16
for c in $(git log --format=%H --reverse "$BASE"..oriole-16); do
  echo "--- cherry-pick $c"
  git cherry-pick "$c" || { echo "[err] cherry-pick 冲突: $c"; exit 1; }
done
git remote remove oriole

echo ">>> 完成: $(git rev-parse --short HEAD) $(git rev-parse --abbrev-ref HEAD)"
git log --oneline -6