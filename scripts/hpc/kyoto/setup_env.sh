#!/bin/bash
# Build a frozen sopran environment for ER batch jobs on a Kyoto University
# supercomputer login node. Compute nodes only activate it; nothing is installed there.
#
#   SOPRAN_SRC=$HOME/src/sopran ENV_ROOT=/LARGE0/grXXXXX/$USER/sopran-env \
#     bash scripts/hpc/kyoto/setup_env.sh
#
# Installs uv and a minimal Rust toolchain under $HOME when missing, creates a
# virtual environment with a pinned numerical stack, and builds sopran (non-editable,
# release Rust extension) from the checkout. Rerun after pulling new commits; use a
# new ENV_ROOT for a new run so that prepared runs keep their code identity.
set -euo pipefail

SOPRAN_SRC=${SOPRAN_SRC:?set SOPRAN_SRC to the sopran git checkout}
ENV_ROOT=${ENV_ROOT:?set ENV_ROOT to the environment directory (e.g. on /LARGE0)}
PYTHON_VERSION=${PYTHON_VERSION:-3.14}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v cargo >/dev/null 2>&1; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
fi
# shellcheck disable=SC1091
source "$HOME/.cargo/env"

mkdir -p "$ENV_ROOT"
uv venv --python "$PYTHON_VERSION" "$ENV_ROOT/venv"
# shellcheck disable=SC1091
source "$ENV_ROOT/venv/bin/activate"
uv pip install -r "$HERE/requirements-er.txt"
uv pip install --no-deps "$SOPRAN_SRC"

git -C "$SOPRAN_SRC" rev-parse HEAD > "$ENV_ROOT/git-head.txt"
git -C "$SOPRAN_SRC" status --short > "$ENV_ROOT/git-status.txt"
git -C "$SOPRAN_SRC" diff > "$ENV_ROOT/git-diff.patch"
python - <<'EOF' | tee "$ENV_ROOT/identity.json"
import json
from sopran.experimental.kaguya import er_batch
print(json.dumps(er_batch.code_identity(), indent=1))
EOF
echo "environment ready: source $ENV_ROOT/venv/bin/activate"
