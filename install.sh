#!/usr/bin/env bash
# ============================================================================
#  LivePaste installer — macOS & Linux
#  made by Nakshtra Yadav
#
#    curl -fsSL https://raw.githubusercontent.com/NakshtraYadav/Live-Paste/main/install.sh | bash
#
#  Installs LivePaste into its own virtual environment (~/.livepaste/venv)
#  and links the `livepaste` command into your PATH.
# ============================================================================

set -euo pipefail

REPO="${LIVEPASTE_REPO:-NakshtraYadav/Live-Paste}"
APP_DIR="$HOME/.livepaste"
VENV_DIR="$APP_DIR/venv"
CONFIG_FILE="$APP_DIR/config"
BIN_LINK_DIRS=("$HOME/.local/bin" "/usr/local/bin")
TOTAL_STEPS=4

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

if [[ "$REPO" == CHANGE_ME* ]]; then
  fail 'Set the repository first:  LIVEPASTE_REPO="owner/repo" bash install.sh'
fi

# --- python check ---
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PY="$cand"; break
  fi
done
if [[ -z "$PY" ]]; then
  if [[ "$(uname)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    printf "  %s!%s Python 3.9+ not found — installing via Homebrew (this can take a minute)\n" "$YELLOW" "$RESET"
    brew install python@3.12 >/dev/null
    PY="python3"
  else
    fail "Python 3.9+ is required. macOS: brew install python  |  Linux: use your package manager."
  fi
fi
printf "  %s✓%s Found %s\n" "$GREEN" "$RESET" "$($PY --version 2>&1)"

# --- interactive choices ---
PORT="$(ask "Which port should LivePaste use?" "8090")"
[[ "$PORT" =~ ^[0-9]+$ ]] || fail "Port must be a number"
INSTALL_DIR="$(ask "Where should LivePaste live?" "$HOME/.livepaste")"
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"
APP_DIR="$INSTALL_DIR"
VENV_DIR="$APP_DIR/venv"
echo

# --- steps ---
mkdir -p "$APP_DIR"
# Advanced: install from a custom source (e.g. a local checkout) instead of GitHub
INSTALL_SOURCE="${LIVEPASTE_INSTALL_SOURCE:-git+https://github.com/$REPO.git}"
run_step 1 "Creating private environment (~/.livepaste/venv)" "$PY" -m venv --clear "$VENV_DIR"
run_step 2 "Preparing installer (pip)" "$VENV_DIR/bin/pip" install --upgrade pip
run_step 3 "Downloading & installing LivePaste from github.com/$REPO" \
  "$VENV_DIR/bin/pip" install --upgrade "$INSTALL_SOURCE"

link_cli() {
  local linked=""
  for dir in "${BIN_LINK_DIRS[@]}"; do
    if { [[ -d "$dir" && -w "$dir" ]] || mkdir -p "$dir" 2>/dev/null; }; then
      ln -sf "$VENV_DIR/bin/livepaste" "$dir/livepaste" && linked="$dir" && break
    fi
  done
  mkdir -p "$(dirname "$CONFIG_FILE")"
  {
    echo "PORT=$PORT"
    echo "REPO=$REPO"
    echo "DATA_DIR=$APP_DIR"
  } > "$CONFIG_FILE"
  [[ -n "$linked" ]]
}
run_step 4 "Linking the livepaste command into your PATH" link_cli

VERSION_INSTALLED="$("$VENV_DIR/bin/livepaste" version 2>/dev/null | head -1 | sed 's/\x1b\[[0-9;]*m//g' | awk '{print $2}')"

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

if ! command -v livepaste >/dev/null 2>&1; then
  if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    printf "\n  %s!%s Add this to your shell profile, then reopen the terminal:\n" "$YELLOW" "$RESET"
    printf "     %sexport PATH=\"\$HOME/.local/bin:\$PATH\"%s\n" "$BOLD" "$RESET"
  fi
fi
echo

if [[ "$INTERACTIVE" == "1" ]]; then
  AUTOSTART="$(ask "Start LivePaste automatically when you log in?" "n")"
  if [[ "$AUTOSTART" =~ ^[Yy] ]]; then
    "$VENV_DIR/bin/livepaste" autostart enable || true
  fi
fi

START_NOW="N"
if [[ "$INTERACTIVE" == "1" ]]; then
  START_NOW="$(ask "Start LivePaste now?" "Y")"
fi
if [[ "$START_NOW" =~ ^[Yy] ]]; then
  echo
  exec "$VENV_DIR/bin/livepaste" start --port "$PORT"
fi
echo
