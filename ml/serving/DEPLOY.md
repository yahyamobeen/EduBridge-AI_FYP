# Retrieval service — deployment

ColQwen2 over the 200 PCTB Physics 9 page scans. One job: answer "which pages match
this string". No auth, no database, no Gemini, no page images — those stay in the
backend. See `tdd.md` §3.2a.

## Why it is a separate process

The model is ~5 GB resident at bfloat16 and the backend runs on a 512 MB instance.
Keeping it here means `backend/requirements.txt` never grows a torch dependency and the
backend's build stays small. The backend reaches it over HTTP and **degrades to its
keyword tier when this service is unreachable**, so an outage here costs answer quality,
not availability.

## Before you build

`pages.colqwen2.pt` (74 MB) must sit next to the `Dockerfile`. It is gitignored
(`*.pt`), because committing curriculum-derived artefacts is a licensing decision nobody
has made. The file is the one encoded on the RTX 5060 across all 200 pages.

**Verify it before building** — the three startup guards will refuse a mispaired file,
but finding that out after a 7 GB image build is a waste of an afternoon:

```bash
python -c "import torch; s=torch.load('pages.colqwen2.pt',map_location='cpu',weights_only=False); print(s['checkpoint'], len(s['pages']), s['embeddings'][0].shape)"
```

Expect `vidore/colqwen2-v1.0 200 torch.Size([755, 128])`.

⚠️ The file may arrive named `pages.colqwen2.pt.zip`. **It is not a zip archive** — a
PyTorch save file is internally a zip and the transfer appended the extension. Rename
it; do not extract it.

## Measure first

This is the number the tutor work has been waiting on. Run it **on the deployment
target**, before wiring anything up:

```bash
python measure.py
```

Then again with the instruction set capped, which is the A/B that tells you whether AMX
is doing the work:

```bash
ONEDNN_MAX_CPU_ISA=AVX512_CORE_BF16 python measure.py
```

Record three things in `tdd.md` §14.2: the **median cached** encode (this is what
NFR-1's 3 s applies to), the **median uncached** encode (a measurement; the contract
sets no budget for it), and **whether `amx_bf16` appeared** in the CPU flags.

⚠️ A result from a laptop is not the deployment number. On a CPU without AVX512-BF16 or
AMX, bfloat16 is a *fit* decision and is measurably **slower** than float32 — 6.1 s was
measured that way on an i5-8265U, and reading that as the ceiling for this approach
would be wrong.

## Run it

| Variable | Default | Notes |
|---|---|---|
| `PAGES_PT` | `/srv/model/pages.colqwen2.pt` | the embeddings |
| `EXPECTED_CHECKPOINT` | `vidore/colqwen2-v1.0` | guard 1 compares the file against this |
| `DTYPE` | `bfloat16` | `float32` needs ~9.4 GB and will not fit on an 8 GiB host |
| `RETRIEVAL_SHARED_SECRET` | — | must match the backend's. Empty disables the check |
| `MAX_WAIT_S` | `15` | ⚠️ keep **below** the backend's 20 s read timeout, or the backend gives up before this service can answer "busy" and degrades for the wrong reason |
| `CACHE_SIZE` | `512` | query embeddings held in memory |
| `TORCH_THREADS` | (torch default) | set to the **physical** core count; hyperthreads make a GEMM-bound workload slower |
| `ANCHOR_PRIOR` | `0.05` | fraction of the score spread, not an absolute bonus |

```bash
docker build -t edubridge-retrieval .
docker run --rm -p 127.0.0.1:8100:8100 \
  -e RETRIEVAL_SHARED_SECRET="$SECRET" -e TORCH_THREADS=2 \
  edubridge-retrieval
```

**One worker, always.** Each worker loads its own copy of the model, so a second one
exhausts memory rather than doubling throughput. Concurrency is handled inside the app:
cache hits run in parallel outside the model lock, and the single forward pass is
lock-serialised with a bounded wait that returns `503`.

## Host: AWS EC2 `m7i.large`

2 vCPU, 8 GiB, Sapphire Rapids — the CPU generation is the whole point, because **AMX
supports only bfloat16 and int8** and makes bf16 the fast path rather than a
compromise. `ap-southeast-1`, the same city as both Render services, so the hop is
1–5 ms.

- **Not t2/t3.** Burstable instances run on CPU credits; sustained inference drains them
  and throttles to a fraction of a core.
- **gp3 root volume, 30 GB.** Never instance store — it is ephemeral, and the image is
  large.
- **EventBridge Scheduler** start 07:50, stop 20:00, weekdays. A *stopped* instance
  costs only EBS (~$2.40/mo) and keeps its disk, so nothing re-downloads. 07:50 allows
  ~60 s boot plus the model load.
- **systemd unit** so the container restarts on boot — scheduled start/stop depends on
  it, and without it the instance comes up silently empty.
- **No GPU.** G and P family vCPU quota defaults to 0 on new accounts and increases are
  slow or refused. Plan for CPU.
- ⚠️ **Check the 6-month account-closure date against your defence date.** AWS closes
  new free-plan accounts at six months and unspent credit is forfeited.

### Networking

**Cloudflare Tunnel** (`cloudflared`) or **Tailscale Funnel**: the host dials outbound,
so there is no inbound port, no public IP, no security-group rule and no certificate to
manage. An ALB plus an ACM certificate would cost ~$16/mo — over half the instance —
for a single service.

Bind the service to **`127.0.0.1`** and let the tunnel daemon reach it. In Docker, the
container's `0.0.0.0` is its own namespace; it is the **published** port that must be
`127.0.0.1:8100:8100`, as above. On a bare VM, pass `--host 127.0.0.1` to uvicorn.

Use **SSM Session Manager** rather than SSH: no open port 22, no keypair. Enforce IMDSv2.

A named Cloudflare tunnel needs a domain on Cloudflare (~$10/yr). A
`trycloudflare.com` quick tunnel needs none but its URL **changes on every restart**,
which breaks a configured `RETRIEVAL_ENDPOINT`. Tailscale Funnel gives a stable
`machine.tailnet.ts.net` hostname with no domain purchase.

## Wire the backend to it

```
RETRIEVAL_MODE=remote
RETRIEVAL_ENDPOINT=https://retrieval.example.com
RETRIEVAL_SHARED_SECRET=<same value>
```

Confirm with `GET /api/tutor/class9/physics/info`, which reports `retriever` as
`remote`, `local` or `heuristic`. **If it says `heuristic`, the keyword index is
answering** — check this service's logs, not the backend's.

## Other hosts

The image is unchanged on any of these; only the wiring differs.

| Host | Shape | Trade-off |
|---|---|---|
| Azure Container Apps | scale-to-zero, free monthly grant | no control over CPU generation, so AMX is luck rather than a decision |
| Google Cloud Run | scale-to-zero, free tier ≈ 12 h/mo at 8 GiB | same CPU-generation caveat |
| Hugging Face Spaces | 16 GB free CPU | verify your account can still run compute Spaces; the terms moved in 2026 |
| A tunnelled laptop | $0 | fine for development. 6.1 s encode, and RAM contention with your editor is the real limit |
| A GPU box | fastest | bf16 is 4.4 GB, so an 8 GB card fits without quantisation |

## Checks

```bash
curl -s localhost:8100/health | python -m json.tool
```

```bash
curl -s -X POST localhost:8100/retrieve -H 'content-type: application/json' \
  -H "X-Retrieval-Secret: $SECRET" \
  -d '{"question":"how does a thermocouple thermometer work","top_k":3}'
```

Ground truth from the verified Chapter 7 transcript — all should come back in the top 3:

| Question | Correct pages |
|---|---|
| how does a thermocouple thermometer work | **154, 155** |
| convert celsius to fahrenheit formula | 154 |
| what is plasma the fourth state of matter | 150 |
| labelled diagram of a laboratory thermometer | 156 |

⚠️ **Correct answers are page *sets*.** The *Thermocouple Thermometer* heading is at the
end of p154 and its body on p155, so both are right — scoring only p155 marks a working
retriever wrong. An adversarial review of our own labels found this.

Also expect **Roman Urdu to outperform English**: "thermocouple kaise kaam karta hai"
carries the English technical term, so it is effectively an English query. Urdu script
transliterates the term away and does worse. That inverts the difficulty ordering most
people assume.

## Failure modes

| Symptom | Cause |
|---|---|
| `checkpoint mismatch ... Refusing to start` | the `.pt` was encoded by a different model. Deliberate: scoring one model's query against another's pages is silent and confidently wrong |
| `does not cover pages 1-200` | a partial encode. Re-encode; do not patch the guard |
| `503 model busy` | more concurrent questions than one serialised model can take. The backend degrades to keyword matching, which is the designed behaviour |
| `401 bad or missing retrieval secret` | `RETRIEVAL_SHARED_SECRET` differs between the two services |
| Every query takes minutes | out of RAM and swapping. Check `DTYPE=bfloat16`, and that nothing else large is on the host |
| Cold start of several minutes | weights not baked in, or the image is being pulled. Both are build-time problems |
