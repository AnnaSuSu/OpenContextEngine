# Optional benchmark reranker

OpenContextEngine calls model services over HTTP. Normal installation does not require running a GPU model server from this repository; configure your own embedding and reranking endpoints as described in [Quick start](QUICKSTART.md).

The published benchmarks used Qwen3-Reranker-4B with an optional batch API. Its [reference server](../scripts/benchmarks/reranker-server.py) is retained with the benchmark tools so the scoring implementation remains inspectable. It loads model weights and runs only on a separately configured Linux CUDA host with `OCE_REMOTE_MODEL_HOST=1`.

## API modes

The paths below belong to this reference server. For another provider, OpenContextEngine appends `/rerank` to `RERANK_BASE_URL`; a `/v1` prefix is only needed if that provider requires it.

| Mode | Endpoint | Request | Response |
| --- | --- | --- | --- |
| Default | `POST /v1/rerank` | `model`, `query`, `documents`, `top_n` | `results` with original document `index` and `relevance_score` |
| Optional batch | `POST /v1/rerank-batch` | `model`, `queries`, `documents`, `pairs` of query/document indices | `results` with original pair `index`, `query_index`, `document_index`, and `relevance_score` |

Both endpoints require `Authorization: Bearer <key>`. Scores are finite values between 0 and 1. The batch implementation shares inference across requested pairs; it does not generate an answer. The published seven-method comparison used `OCE_RERANK_API=rerank-batch`; ordinary services use `OCE_RERANK_API=rerank`.

The reference server exposes unauthenticated readiness through `GET /healthz` and authenticated model metadata through `GET /v1/models`. It reports truncation and rejects invalid inputs. Its source defines input, batch, body-size, concurrency, and timeout limits.

## Reference environment

The recorded benchmark deployment used Python 3.12, PyTorch 2.7.1 with CUDA 12.8, Transformers 4.57.6, and BF16 inference. The server additionally imports FastAPI and Pydantic and needs an ASGI runner such as Uvicorn. These model-server dependencies are separate from the client requirements.

The operator supplies `RERANK_MODEL_DIR` pointing to pre-provisioned Qwen3-Reranker-4B weights and `RERANK_API_KEY` with at least 24 characters. Loading is local-only with remote model code disabled. Optional batch settings are `RERANK_MAX_BATCH` and `RERANK_BATCH_TOKEN_BUDGET`.

On that Linux model host, from this repository's root:

```sh
# Set the model directory and secret in the server's environment first.
OCE_REMOTE_MODEL_HOST=1 python -m uvicorn reranker-server:app \
  --app-dir scripts/benchmarks --host 127.0.0.1 --port 8000
```

Use an HTTPS proxy or explicitly configured secure transport for remote clients. Personal service addresses, Supervisor configuration, and deployment logs are not part of the public example. No deployment or model download is performed by installing OpenContextEngine.
