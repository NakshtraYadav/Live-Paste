#!/usr/bin/env bash
# ============================================================================
#  LivePaste installer — macOS & Linux
#  made by Nakshtra Yadav
#
#    curl -fsSL https://raw.githubusercontent.com/NakshtraYadav/Live-Paste/main/install.sh | bash
#
#  Prefers the prebuilt standalone binary (no Python needed!). Falls back to
#  a pip install inside a private virtualenv when no binary release exists.
# ============================================================================

set -euo pipefail

REPO="${LIVEPASTE_REPO:-NakshtraYadav/Live-Paste}"
APP_DIR="$HOME/.livepaste"
CONFIG_FILE="$HOME/.livepaste/config"
BIN_LINK_DIRS=("$HOME/.local/bin" "/usr/local/bin")

# ---------------------------------------------------------------- terminal --
# Interactive only when we have a real terminal to read from AND write to
INTERACTIVE=0
if [[ -t 1 && -r /dev/tty ]]; then INTERACTIVE=1; fi

if [[ -t 1 ]] || [[ "${FORCE_COLOR:-}" == "1" ]]; then
  TEAL=$'\033[38;5;37m'; CYAN=$'\033[38;5;44m'; DIM=$'\033[2m'
  BOLD=$'\033[1m'; GREEN=$'\033[38;5;42m'; RED=$'\033[38;5;203m'
  YELLOW=$'\033[38;5;221m'; RESET=$'\033[0m'
  ANIMATE=1
else
  TEAL=""; CYAN=""; DIM=""; BOLD=""; GREEN=""; RED=""; YELLOW=""; RESET=""
  ANIMATE=0
fi

fail() { printf "%s✗ %s%s\n" "$RED" "$*" "$RESET" >&2; exit 1; }

banner() {
  printf "\n%s%s" "$TEAL" "$BOLD"
  cat <<'EOF'
   __    _  _  _  ____  ____   __   ___  ____  ____
  (  )  ( \/ )( \(  __)(  _ \ / _\ / __)(_  _)(  __)
  / (_/\ )  /  \ \) _)  ) __//    \\__ \  )(   ) _)
  \____/(__/ \__/(____)(__)  \_/\_/(___/ (__) (____)
EOF
  printf "%s" "$RESET"
  printf "  %s%sShare text & code on your network — in real time.%s\n" "$DIM" "$CYAN" "$RESET"
  printf "  %smade by %s%sNakshtra Yadav%s\n\n" "$DIM" "$RESET" "$BOLD" "$RESET"
}

TOTAL_STEPS=2

# run_step <step-number> <label> <command...>
run_step() {
  local n="$1" label="$2"; shift 2
  local log; log="$(mktemp)"
  local frames='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'

  if [[ "$ANIMATE" == "1" ]]; then
    ("$@" > "$log" 2>&1) &
    local pid=$!
    local i=0
    while kill -0 "$pid" 2>/dev/null; do
      local frame="${frames:$((i % 10)):1}"
      printf "\r  %s[%s/%s]%s %s%s%s %s " "$DIM" "$n" "$TOTAL_STEPS" "$RESET" "$TEAL" "$frame" "$RESET" "$label"
      sleep 0.09
      i=$((i + 1))
    done
    if wait "$pid"; then
      printf "\r  %s[%s/%s]%s %s✓%s %s   \n" "$DIM" "$n" "$TOTAL_STEPS" "$RESET" "$GREEN" "$RESET" "$label"
    else
      printf "\r  %s[%s/%s]%s %s✗%s %s   \n\n" "$DIM" "$n" "$TOTAL_STEPS" "$RESET" "$RED" "$RESET" "$label"
      sed 's/^/    /' "$log" | tail -20
      rm -f "$log"
      fail "Install failed at: $label"
    fi
  else
    printf "  [%s/%s] %s ...\n" "$n" "$TOTAL_STEPS" "$label"
    if ! "$@" > "$log" 2>&1; then
      sed 's/^/    /' "$log" | tail -20
      rm -f "$log"
      fail "Install failed at: $label"
    fi
  fi
  rm -f "$log"
}

ask() { # ask <question> <default>  -> echoes answer
  local q="$1" def="$2" ans=""
  if [[ "$INTERACTIVE" == "1" ]]; then
    printf "  %s?%s %s %s[%s]%s " "$YELLOW" "$RESET" "$q" "$DIM" "$def" "$RESET" > /dev/tty
    read -r ans < /dev/tty || true
  fi
  echo "${ans:-$def}"
}

# ------------------------------------------------------------------- start --
banner

# --- interactive choices ---
PORT="$(ask "Which port should LivePaste use?" "8090")"
[[ "$PORT" =~ ^[0-9]+$ ]] || fail "Port must be a number"
INSTALL_DIR="$(ask "Where should LivePaste live?" "$HOME/.livepaste")"
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"
APP_DIR="$INSTALL_DIR"
echo

# --- pick install method: prebuilt binary (no Python!) or pip fallback ---
OS="$(uname -s)"; MACHINE="$(uname -m)"
case "$MACHINE" in
  arm64|aarch64) ARCH="arm64" ;;
  x86_64|amd64)  ARCH="x86_64" ;;
  *)             ARCH="" ;;
esac
ASSET=""
case "$OS" in
  Darwin) [[ -n "$ARCH" ]] && ASSET="livepaste-macos-$ARCH" ;;
  Linux)  [[ -n "$ARCH" ]] && ASSET="livepaste-linux-$ARCH" ;;
esac

BINARY_URL=""
if [[ -n "$ASSET" && "${LIVEPASTE_FORCE_PYTHON:-0}" != "1" ]]; then
  CANDIDATE="https://github.com/$REPO/releases/latest/download/$ASSET"
  if curl -fsIL --max-time 10 -o /dev/null "$CANDIDATE" 2>/dev/null; then
    BINARY_URL="$CANDIDATE"
  fi
fi

LIVEPASTE_BIN=""
mkdir -p "$APP_DIR"

write_config() {
  mkdir -p "$(dirname "$CONFIG_FILE")"
  {
    echo "PORT=$PORT"
    echo "REPO=$REPO"
    echo "DATA_DIR=$APP_DIR"
  } > "$CONFIG_FILE"
}

link_cli() {
  local linked=""
  local candidates=()
  # 1st choice: directories that are ALREADY on PATH and writable (no profile edits needed)
  local IFS=':'
  for dir in $PATH; do
    case "$dir" in
      "$HOME"/*|/usr/local/bin|/opt/homebrew/bin)
        if [[ -d "$dir" && -w "$dir" ]]; then candidates+=("$dir"); fi
        ;;
    esac
  done
  unset IFS
  # Fallbacks (may need a PATH update, handled after install)
  candidates+=("${BIN_LINK_DIRS[@]}")
  for dir in "${candidates[@]}"; do
    if { [[ -d "$dir" && -w "$dir" ]] || mkdir -p "$dir" 2>/dev/null; }; then
      ln -sf "$LIVEPASTE_BIN" "$dir/livepaste" && linked="$dir" && break
    fi
  done
  write_config
  [[ -n "$linked" ]]
}

find_link_dir() { # where did the livepaste symlink end up?
  local IFS=':'
  for dir in $PATH; do
    [[ -x "$dir/livepaste" ]] && { echo "$dir"; return; }
  done
  unset IFS
  for dir in "${BIN_LINK_DIRS[@]}"; do
    [[ -x "$dir/livepaste" ]] && { echo "$dir"; return; }
  done
  echo ""
}

shell_profile() {
  case "${SHELL:-}" in
    */zsh)  echo "$HOME/.zshrc" ;;
    */bash) if [[ "$(uname -s)" == "Darwin" ]]; then echo "$HOME/.bash_profile"; else echo "$HOME/.bashrc"; fi ;;
    *)      echo "$HOME/.profile" ;;
  esac
}

# Make sure the `livepaste` command is reachable; fix PATH automatically if not
ensure_on_path() {
  PATH_FIX_NOTE=""
  if command -v livepaste >/dev/null 2>&1; then
    return
  fi
  local link_dir; link_dir="$(find_link_dir)"
  if [[ -z "$link_dir" ]]; then
    PATH_FIX_NOTE="manual"
    return
  fi
  if [[ ":$PATH:" == *":$link_dir:"* ]]; then
    return
  fi
  local profile; profile="$(shell_profile)"
  if ! grep -qs "livepaste" "$profile" 2>/dev/null || ! grep -qs "$link_dir" "$profile" 2>/dev/null; then
    {
      echo ""
      echo "# Added by the LivePaste installer (makes the 'livepaste' command available)"
      echo "export PATH=\"$link_dir:\$PATH\""
    } >> "$profile"
  fi
  export PATH="$link_dir:$PATH"
  PATH_FIX_NOTE="$profile"
}

if [[ -n "$BINARY_URL" ]]; then
  # ------------------------- binary install (no Python) --------------------
  printf "  %s✓%s Standalone app available for %s — %sno Python needed!%s\n\n" "$GREEN" "$RESET" "$OS/$ARCH" "$BOLD" "$RESET"
  TOTAL_STEPS=2
  LIVEPASTE_BIN="$APP_DIR/bin/livepaste"

  download_binary() {
    mkdir -p "$APP_DIR/bin"
    curl -fSL --progress-bar -o "$LIVEPASTE_BIN.tmp" "$BINARY_URL"
    chmod +x "$LIVEPASTE_BIN.tmp"
    mv "$LIVEPASTE_BIN.tmp" "$LIVEPASTE_BIN"
    if [[ "$OS" == "Darwin" ]]; then
      xattr -d com.apple.quarantine "$LIVEPASTE_BIN" 2>/dev/null || true
    fi
  }
  run_step 1 "Downloading the LivePaste app" download_binary
  run_step 2 "Linking the livepaste command into your PATH" link_cli
else
  # -------------------------- pip install fallback --------------------------
  printf "  %s!%s No prebuilt app for %s yet — installing with Python instead.\n\n" "$YELLOW" "$RESET" "${OS}/${ARCH:-unknown}"
  TOTAL_STEPS=4
  VENV_DIR="$APP_DIR/venv"
  LIVEPASTE_BIN="$VENV_DIR/bin/livepaste"

  PY=""
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      PY="$cand"; break
    fi
  done
  if [[ -z "$PY" ]]; then
    if [[ "$OS" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
      printf "  %s!%s Python 3.9+ not found — installing via Homebrew (this can take a minute)\n" "$YELLOW" "$RESET"
      brew install python@3.12 >/dev/null
      PY="python3"
    else
      fail "Python 3.9+ is required. macOS: brew install python  |  Linux: use your package manager."
    fi
  fi
  printf "  %s✓%s Found %s\n" "$GREEN" "$RESET" "$($PY --version 2>&1)"

  INSTALL_SOURCE="${LIVEPASTE_INSTALL_SOURCE:-git+https://github.com/$REPO.git}"
  run_step 1 "Creating private environment" "$PY" -m venv --clear "$VENV_DIR"
  run_step 2 "Preparing installer (pip)" "$VENV_DIR/bin/pip" install --upgrade pip
  run_step 3 "Downloading & installing LivePaste from github.com/$REPO" \
    "$VENV_DIR/bin/pip" install --upgrade "$INSTALL_SOURCE"
  run_step 4 "Linking the livepaste command into your PATH" link_cli
fi

VERSION_INSTALLED="$("$LIVEPASTE_BIN" version 2>/dev/null | head -1 | sed 's/\x1b\[[0-9;]*m//g' | awk '{print $2}')"

ensure_on_path

# --- summary ---
echo
printf "  %s%s╭───────────────────────────────────────────────╮%s\n" "$TEAL" "$BOLD" "$RESET"
printf "  %s%s│%s  %sLivePaste %s installed successfully!%s\n" "$TEAL" "$BOLD" "$RESET" "$GREEN" "${VERSION_INSTALLED:-}" "$RESET"
printf "  %s%s│%s\n" "$TEAL" "$BOLD" "$RESET"
printf "  %s%s│%s   Start:      %slivepaste start%s\n" "$TEAL" "$BOLD" "$RESET" "$BOLD" "$RESET"
printf "  %s%s│%s   Update:     %slivepaste update%s\n" "$TEAL" "$BOLD" "$RESET" "$BOLD" "$RESET"
printf "  %s%s│%s   Settings:   %slivepaste config%s  %s(port, data-dir, ...)%s\n" "$TEAL" "$BOLD" "$RESET" "$BOLD" "$RESET" "$DIM" "$RESET"
printf "  %s%s│%s   Location:   %s\n" "$TEAL" "$BOLD" "$RESET" "$APP_DIR"
printf "  %s%s╰───────────────────────────────────────────────╯%s\n" "$TEAL" "$BOLD" "$RESET"

if [[ "$PATH_FIX_NOTE" == "manual" ]]; then
  printf "\n  %s!%s Could not link into your PATH. Start LivePaste with:\n" "$YELLOW" "$RESET"
  printf "     %s%s start%s\n" "$BOLD" "$LIVEPASTE_BIN" "$RESET"
elif [[ -n "$PATH_FIX_NOTE" ]]; then
  printf "\n  %s✓%s Added the livepaste command to your PATH %s(saved in %s)%s\n" "$GREEN" "$RESET" "$DIM" "$PATH_FIX_NOTE" "$RESET"
  printf "    Open a %snew terminal window%s (or run %ssource %s%s) before using it.\n" "$BOLD" "$RESET" "$BOLD" "$PATH_FIX_NOTE" "$RESET"
fi
echo

if [[ "$INTERACTIVE" == "1" ]]; then
  AUTOSTART="$(ask "Start LivePaste automatically when you log in?" "n")"
  if [[ "$AUTOSTART" =~ ^[Yy] ]]; then
    "$LIVEPASTE_BIN" autostart enable || true
  fi
fi

START_NOW="N"
if [[ "$INTERACTIVE" == "1" ]]; then
  START_NOW="$(ask "Start LivePaste now?" "Y")"
fi
if [[ "$START_NOW" =~ ^[Yy] ]]; then
  echo
  exec "$LIVEPASTE_BIN" start --port "$PORT"
fi
echo
