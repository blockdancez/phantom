#!/usr/bin/env bash
# install.sh — Phantom AutoDev 安装脚本（双模式）
#
# 模式 1（本地）：在仓库目录里运行
#   ./install.sh                    # 自动选择目标
#   ./install.sh /opt/bin/phantom   # 指定目标路径
#   ./install.sh --uninstall        # 卸载
#
# 模式 2（远程一行安装）：通过 curl 运行
#   curl -fsSL https://raw.githubusercontent.com/blockdancez/phantom/main/install.sh | bash

set -euo pipefail

REPO_URL="https://github.com/blockdancez/phantom.git"
REPO_DIR_DEFAULT="$HOME/.phantom-autodev"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log() { echo -e "${CYAN}[install]${NC} $*"; }
ok()  { echo -e "${GREEN}[ok]${NC} $*"; }
warn(){ echo -e "${YELLOW}[warn]${NC} $*"; }
err() { echo -e "${RED}[err]${NC} $*" >&2; }

# ── 判断模式：脚本同目录是否存在 phantom.sh ────────────────
SELF_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" ]] && [[ -f "${BASH_SOURCE[0]}" ]]; then
  SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [[ -n "$SELF_DIR" ]] && [[ -f "$SELF_DIR/phantom.sh" ]]; then
  # 本地模式
  SCRIPT_DIR="$SELF_DIR"
else
  # 远程模式：clone 或更新仓库
  log "远程安装模式"

  if ! command -v git >/dev/null 2>&1; then
    err "需要 git，请先安装"
    exit 1
  fi

  SCRIPT_DIR="${PHANTOM_INSTALL_DIR:-$REPO_DIR_DEFAULT}"

  if [[ -d "$SCRIPT_DIR/.git" ]]; then
    log "更新已有仓库：$SCRIPT_DIR"
    git -C "$SCRIPT_DIR" pull --ff-only || warn "git pull 失败，将使用当前版本"
  else
    log "克隆仓库到：$SCRIPT_DIR"
    rm -rf "$SCRIPT_DIR"
    git clone --depth 1 "$REPO_URL" "$SCRIPT_DIR"
  fi

  if [[ ! -f "$SCRIPT_DIR/phantom.sh" ]]; then
    err "仓库里没找到 phantom.sh：$SCRIPT_DIR"
    exit 1
  fi
fi

REPO_PHANTOM="$SCRIPT_DIR/phantom.sh"
chmod +x "$REPO_PHANTOM"

# ── 解析参数 ─────────────────────────────────────────────
UNINSTALL=false
TARGET=""
for arg in "$@"; do
  case "$arg" in
    --uninstall|-u) UNINSTALL=true ;;
    -h|--help)
      sed -n '2,12p' "${BASH_SOURCE[0]:-$0}"
      exit 0 ;;
    *) TARGET="$arg" ;;
  esac
done

# ── 自动挑选目标 ────────────────────────────────────────
pick_target() {
  local candidates=(
    "/usr/local/bin/phantom"
    "$HOME/.local/bin/phantom"
    "$HOME/bin/phantom"
  )
  for c in "${candidates[@]}"; do
    local d
    d="$(dirname "$c")"
    if [[ -d "$d" && -w "$d" ]] || mkdir -p "$d" 2>/dev/null; then
      if [[ -w "$d" ]]; then
        echo "$c"
        return 0
      fi
    fi
  done
  mkdir -p "$HOME/.local/bin"
  echo "$HOME/.local/bin/phantom"
}

if [[ -z "$TARGET" ]]; then
  TARGET="$(pick_target)"
fi
TARGET_DIR="$(dirname "$TARGET")"

# ── 卸载 ────────────────────────────────────────────────
if [[ "$UNINSTALL" == true ]]; then
  if [[ -L "$TARGET" || -f "$TARGET" ]]; then
    rm -f "$TARGET"
    ok "已卸载：$TARGET"
  else
    warn "未找到：$TARGET"
  fi
  exit 0
fi

# ── 依赖检查 ────────────────────────────────────────────
check_dep() {
  if command -v "$1" >/dev/null 2>&1; then
    ok "已安装：$1"
  else
    warn "缺少依赖：$1 ${2:-}"
  fi
}
log "检查依赖..."
if command -v claude >/dev/null 2>&1 || command -v codex >/dev/null 2>&1; then
  ok "已安装 claude 或 codex CLI"
else
  warn "缺少 claude 或 codex CLI（至少需要一个）"
fi
check_dep jq
check_dep python3
check_dep curl

# ── 安装 ────────────────────────────────────────────────
mkdir -p "$TARGET_DIR"

if [[ -e "$TARGET" || -L "$TARGET" ]]; then
  if [[ -L "$TARGET" && "$(readlink "$TARGET")" == "$REPO_PHANTOM" ]]; then
    ok "已经安装到 ${TARGET}，无需重复"
  else
    warn "$TARGET 已存在，将覆盖"
    rm -f "$TARGET"
  fi
fi

if [[ ! -e "$TARGET" ]]; then
  ln -s "$REPO_PHANTOM" "$TARGET"
  ok "已安装：$TARGET → $REPO_PHANTOM"
fi

# ── PATH 检查 ───────────────────────────────────────────
case ":$PATH:" in
  *":$TARGET_DIR:"*)
    ok "$TARGET_DIR 已在 PATH 中，可以直接使用：${CYAN}phantom${NC}"
    ;;
  *)
    warn "$TARGET_DIR 不在 PATH 中"
    echo ""
    echo "请把下面这行加进你的 shell 配置（~/.zshrc 或 ~/.bashrc）："
    echo ""
    echo "  export PATH=\"$TARGET_DIR:\$PATH\""
    echo ""
    echo "然后 ${CYAN}source ~/.zshrc${NC}（或重开终端）"
    ;;
esac

echo ""
log "使用示例："
echo "  cd /path/to/my-workspace"
echo "  phantom 'Todo API, Node.js + Express, 端口 3000'"
echo ""
log "项目会生成在**当前目录**下。"
