#!/usr/bin/env bash
# One-time setup for the book-indexing tool on a Linux machine with an NVIDIA GPU.
# Same steps as setup.bat: .venv here, the CUDA torch build that matches the driver, then
# the pinned packages. Safe to run again.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v nvidia-smi >/dev/null; then
    echo "No nvidia-smi found. Install the NVIDIA driver, then run this again." >&2
    exit 1
fi
driver_major=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | cut -d. -f1)
echo "== NVIDIA driver major version: ${driver_major}"
if [ "${driver_major}" -ge 580 ]; then
    index=https://download.pytorch.org/whl/cu130
    torch_pin="torch==2.13.0+cu130"
    vision_pin="torchvision==0.28.0+cu130"
else
    echo "   driver older than R580: using the CUDA 12.8 build"
    index=https://download.pytorch.org/whl/cu128
    torch_pin="torch==2.11.0+cu128"
    vision_pin="torchvision==0.26.0+cu128"
fi

python=python3.12
command -v "${python}" >/dev/null || { echo "python3.12 not found" >&2; exit 1; }
[ -x .venv/bin/python ] || "${python}" -m venv .venv
vpy=.venv/bin/python
"${vpy}" -m pip install --upgrade pip
# Never a plain "pip install torch" from PyPI for this: pin the CUDA build explicitly.
"${vpy}" -m pip install "${torch_pin}" "${vision_pin}" --index-url "${index}"
"${vpy}" -c "import torch, torchvision; print('torch==' + torch.__version__); print('torchvision==' + torchvision.__version__)" > .torch-constraint.txt
"${vpy}" -m pip install -r requirements.txt -r requirements-figures.txt -c constraints.txt -c .torch-constraint.txt
"${vpy}" -c "import torch; print('torch', torch.__version__, '| CUDA available:', torch.cuda.is_available())"
echo
echo "Setup done. Next:  .venv/bin/python encode_books.py calibrate"
