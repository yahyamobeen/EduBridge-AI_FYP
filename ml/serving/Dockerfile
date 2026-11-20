# ColQwen2 retrieval service (tdd.md §3.2a).
#
# Builds a self-contained image: model weights AND page embeddings are baked in, so a
# cold start loads from local disk instead of downloading ~5 GB from Hugging Face. On a
# host that scales to zero or stops on a schedule, that is the difference between a
# cold start of a couple of minutes and one of twenty.
#
#   docker build -t edubridge-retrieval .
#   docker run --rm -p 8100:8100 -e RETRIEVAL_SHARED_SECRET=... edubridge-retrieval
#
# ⚠️ BUILD PREREQUISITE: pages.colqwen2.pt (74 MB) must sit next to this Dockerfile.
# It is gitignored (*.pt) because committing curriculum-derived artefacts to the
# repository is a licensing decision nobody has made. Copy it in before building.

FROM python:3.12-slim

# torch first, in its own layer, from the CPU-only index. This layer is ~200 MB instead
# of the ~2.5 GB a default install produces, and it caches across rebuilds because it
# changes far less often than the application code.
RUN pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu \
      "torch>=2.4.0"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download the model at BUILD time into the image's HF cache. Without this the
# first request after every cold start fetches ~5 GB, which is both slow and a runtime
# dependency on Hugging Face being reachable.
ENV HF_HOME=/opt/hf
ARG CHECKPOINT=vidore/colqwen2-v1.0
ENV CHECKPOINT=${CHECKPOINT}
# The same pinned revisions app.py loads (PINNED_REVISIONS) - otherwise the cache holds
# `main` and the service downloads the pinned ones at its first start anyway.
ARG ADAPTER_REVISION=2b6ac8fb37f46a49e4841e599583d00ae8a20117
ARG BASE_REVISION=9fe8a713422a7cb4ef79ca77a09b381ee2243101
RUN python -c "import os; from huggingface_hub import snapshot_download; \
from colpali_engine.models import ColQwen2, ColQwen2Processor; \
a = snapshot_download(os.environ['CHECKPOINT'], revision='${ADAPTER_REVISION}'); \
ColQwen2.from_pretrained(a, revision='${BASE_REVISION}', device_map='cpu'); \
ColQwen2Processor.from_pretrained(a); print('cached', a)"

WORKDIR /srv
COPY app.py measure.py ./
COPY pages.colqwen2.pt /srv/model/pages.colqwen2.pt

ENV PAGES_PT=/srv/model/pages.colqwen2.pt \
    EXPECTED_CHECKPOINT=${CHECKPOINT} \
    DTYPE=bfloat16 \
    PYTHONUNBUFFERED=1

# Not root. The service reads two files and answers HTTP; it needs nothing else.
RUN useradd --create-home --uid 10001 retrieval && chown -R retrieval /srv /opt/hf
USER retrieval

EXPOSE 8100

# ⚠️ ONE worker, always. Each worker loads its own ~5 GB copy of the model, so a second
# one does not double throughput - it exhausts memory and the kernel kills the process.
# Concurrency is handled inside the app: cache hits run in parallel, and the single
# forward pass is lock-serialised with a bounded wait.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1"]
