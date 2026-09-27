#!/bin/sh
# obscura-c7 安装脚本
# 把包内容复制到 PREFIX,并把入口脚本链接进 BIN_DIR。
# 不修改任何 shell 配置文件;若 BIN_DIR 不在 PATH 中,仅打印提示。
#
# 可用环境变量覆盖默认位置:
#   OBSCURA_C7_PREFIX   安装目录(默认 ~/.local/share/obscura-c7)
#   OBSCURA_C7_BIN_DIR  链接目录(默认 ~/.local/bin)
set -eu

SRC=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PREFIX="${OBSCURA_C7_PREFIX:-$HOME/.local/share/obscura-c7}"
BIN_DIR="${OBSCURA_C7_BIN_DIR:-$HOME/.local/bin}"

echo ">> install: $SRC -> $PREFIX"
rm -rf "$PREFIX"
mkdir -p "$PREFIX" "$BIN_DIR"
cp -r "$SRC/bin" "$SRC/lib" "$PREFIX/"
cp "$SRC/obscura_c7" "$PREFIX/obscura_c7"
[ -f "$SRC/README.md" ] && cp "$SRC/README.md" "$PREFIX/README.md"
chmod +x "$PREFIX/obscura_c7" "$PREFIX/bin/obscura_c7" "$PREFIX/bin/obscura-worker"

ln -sf "$PREFIX/obscura_c7" "$BIN_DIR/obscura_c7"
echo ">> linked: $BIN_DIR/obscura_c7 -> $PREFIX/obscura_c7"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    echo
    echo "!! $BIN_DIR 不在 PATH 中,请自行添加(按你的 shell 选择其一):"
    echo "     echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc   # bash"
    echo "     echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.zshrc    # zsh"
    echo "   然后重新登录或 source 对应文件。"
    ;;
esac

echo
echo ">> done. verify with: obscura_c7 --version"
