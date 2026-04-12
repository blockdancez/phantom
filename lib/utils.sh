#!/usr/bin/env bash
# lib/utils.sh - 通用工具函数

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }
log_phase() { echo -e "\n${CYAN}========== $* ==========${NC}\n"; }

# 检查依赖
check_dependencies() {
  local missing=()

  # AI 后端：至少有一个即可
  local backend="${PHANTOM_BACKEND:-}"
  if [[ "$backend" == "claude" ]]; then
    command -v claude &>/dev/null || missing+=("claude")
  elif [[ "$backend" == "codex" ]]; then
    command -v codex &>/dev/null || missing+=("codex")
  else
    # 自动检测：至少有一个
    if ! command -v claude &>/dev/null && ! command -v codex &>/dev/null; then
      missing+=("claude 或 codex")
    fi
  fi

  for cmd in jq docker python3; do
    if ! command -v "$cmd" &>/dev/null; then
      missing+=("$cmd")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    log_error "缺少依赖: ${missing[*]}"
    exit 1
  fi
}

# 获取项目根目录（phantom-dev.sh 所在目录）
get_script_dir() {
  cd "$(dirname "${BASH_SOURCE[1]}")" && pwd
}
