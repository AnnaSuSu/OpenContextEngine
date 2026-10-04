"""Optional Linux GPU reranker used by the published benchmarks.

ModelScope supplies the weights. Scoring follows Qwen's yes/no logit protocol:
https://github.com/QwenLM/Qwen3-Embedding
"""
import os
import sys

if sys.platform != 'linux' or os.environ.get('OCE_REMOTE_MODEL_HOST', os.environ.get('REPONERVE_REMOTE_MODEL_HOST')) != '1':
    raise RuntimeError('Run this optional model server on Linux with OCE_REMOTE_MODEL_HOST=1')

import asyncio
import hashlib
import json
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import torch
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_ID = 'Qwen3-Reranker-4B'
MODEL_DIR = Path(os.environ['RERANK_MODEL_DIR'])
API_KEY = os.environ['RERANK_API_KEY']
MAX_LENGTH = 8192
MAX_BATCH = int(os.environ.get('RERANK_MAX_BATCH', '32'))
if not 1 <= MAX_BATCH <= 64:
    raise RuntimeError('RERANK_MAX_BATCH must be between 1 and 64')
BATCH_TOKEN_BUDGET = int(os.environ.get('RERANK_BATCH_TOKEN_BUDGET', '8192'))
if not 8192 <= BATCH_TOKEN_BUDGET <= 32768:
    raise RuntimeError('RERANK_BATCH_TOKEN_BUDGET must be between 8192 and 32768')
SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
INSTRUCTION = 'Given a software development question, retrieve code passages that help answer the question, including relevant implementation details.'
PREFIX = '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
state = {'ready': False}
lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app):
    if len(API_KEY) < 24 or not torch.cuda.is_available():
        raise RuntimeError('A strong API key and remote CUDA GPU are required')
    torch.set_num_threads(4)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, padding_side='left', local_files_only=True, trust_remote_code=False)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_DIR, dtype=torch.bfloat16, attn_implementation='sdpa',
        local_files_only=True, trust_remote_code=False, use_safetensors=True,
    ).to('cuda').eval()
    state.update(tokenizer=tokenizer, model=model,
                 prefix=tokenizer.encode(PREFIX, add_special_tokens=False),
                 suffix=tokenizer.encode(SUFFIX, add_special_tokens=False),
                 yes=tokenizer.convert_tokens_to_ids('yes'), no=tokenizer.convert_tokens_to_ids('no'))
    if state['yes'] == state['no'] or tokenizer.unk_token_id in [state['yes'], state['no']]:
        raise RuntimeError('Invalid yes/no scoring tokens')
    state['ready'] = True
    yield
    state['ready'] = False


app = FastAPI(title='OpenContextEngine Remote Reranker', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


class RerankRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: str = MODEL_ID
    query: str = Field(min_length=1, max_length=8192)
    documents: list[Annotated[str, Field(min_length=1, max_length=200000)]] = Field(min_length=1, max_length=128)
    top_n: int | None = Field(default=None, ge=1, le=128)
    return_documents: bool = False
    instruction: str | None = Field(default=None, min_length=1, max_length=2000)


class PairBatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: str = MODEL_ID
    queries: list[Annotated[str, Field(min_length=1, max_length=8192)]] = Field(min_length=1, max_length=8)
    documents: list[Annotated[str, Field(min_length=1, max_length=200000)]] = Field(min_length=1, max_length=192)
    pairs: list[tuple[int, int]] = Field(min_length=1, max_length=384)
    instruction: str | None = Field(default=None, min_length=1, max_length=2000)
    max_batch_size: int = Field(default=MAX_BATCH, ge=1, le=MAX_BATCH)


def authorize(authorization: Annotated[str | None, Header()] = None):
    if not secrets.compare_digest(authorization or '', f'Bearer {API_KEY}'):
        raise HTTPException(status_code=401, detail='Unauthorized')


@app.middleware('http')
async def bounded_body(request, call_next):
    from starlette.responses import JSONResponse
    try:
        size = int(request.headers.get('content-length', '0'))
    except ValueError:
        return JSONResponse({'detail': 'Invalid content length'}, status_code=400)
    if request.method == 'POST' and (size <= 0 or size > 4_000_000):
        return JSONResponse({'detail': 'Request must have a content length between 1 and 4000000'}, status_code=413)
    return await call_next(request)


@app.get('/healthz')
def health():
    return {'status': 'ok' if state['ready'] else 'loading', 'model_loaded': state['ready'],
            'model': MODEL_ID, 'source': 'ModelScope', 'max_input_tokens': MAX_LENGTH,
            'dtype': 'bfloat16', 'max_documents': 128, 'max_batch_size': MAX_BATCH,
            'batch_token_budget': BATCH_TOKEN_BUDGET, 'scoring': 'softmax(no,yes)', 'pair_batch': True,
            'source_sha256': SOURCE_SHA256,
            'instruction_sha256': hashlib.sha256(INSTRUCTION.encode()).hexdigest()}


@app.get('/v1/models', dependencies=[Depends(authorize)])
def models():
    return {'object': 'list', 'data': [{'id': MODEL_ID, 'object': 'model', 'owned_by': 'Qwen'}]}


def score_pairs(queries, documents, pairs, instruction=None, max_batch_size=MAX_BATCH):
    started = time.monotonic()
    tokenizer = state['tokenizer']
    instruction = instruction or INSTRUCTION
    prefix, suffix = state['prefix'], state['suffix']
    allowance = MAX_LENGTH-len(prefix)-len(suffix)
    encoded, truncated = [], []
    for i, (query_index, document_index) in enumerate(pairs):
        text = f'<Instruct>: {instruction}\n<Query>: {queries[query_index]}\n<Document>: {documents[document_index]}'
        tokens = tokenizer.encode(text, add_special_tokens=False)
        if len(tokens) > allowance:
            truncated.append(i)
        encoded.append(prefix+tokens[:allowance]+suffix)
    # Group by length for padding efficiency; original indices are preserved.
    order = sorted(range(len(encoded)), key=lambda i: len(encoded[i]))
    scores = [None]*len(encoded)
    offset = 0
    with torch.inference_mode():
        while offset < len(order):
            if time.monotonic()-started > 90:
                raise TimeoutError('Rerank deadline')
            batch = []
            while offset < len(order) and len(batch) < max_batch_size:
                index = order[offset]
                if batch and len(encoded[index])*(len(batch)+1) > BATCH_TOKEN_BUDGET:
                    break
                batch.append(index); offset += 1
            inputs = tokenizer.pad({'input_ids': [encoded[i] for i in batch]}, padding=True, return_tensors='pt').to('cuda')
            # Computing only the last-position logits avoids a vocabulary-sized
            # tensor for every input token; no generation or KV cache is needed.
            logits = state['model'](**inputs, use_cache=False, logits_to_keep=1).logits[:, -1, :]
            values = torch.softmax(logits[:, [state['no'], state['yes']]].float(), dim=-1)[:, 1].cpu().tolist()
            if not all(0 <= value <= 1 for value in values):
                raise RuntimeError('Invalid relevance scores')
            for index, value in zip(batch, values):
                scores[index] = value
    results = [{'index': i, 'query_index': pairs[i][0], 'document_index': pairs[i][1], 'relevance_score': value} for i, value in enumerate(scores)]
    return {'id': secrets.token_hex(12), 'model': MODEL_ID, 'results': results,
            'usage': {'input_tokens': sum(map(len, encoded))},
            'meta': {'truncated_documents': truncated, 'max_input_tokens': MAX_LENGTH,
                     'elapsed_ms': round((time.monotonic()-started)*1000), 'pairs': len(pairs),
                     'max_batch_size': max_batch_size, 'batch_token_budget': BATCH_TOKEN_BUDGET,
                     'instruction_sha256': hashlib.sha256(instruction.encode()).hexdigest()}}


def score(body):
    result = score_pairs([body.query], body.documents, [(0, i) for i in range(len(body.documents))], body.instruction)
    results = sorted([{'index': row['document_index'], 'relevance_score': row['relevance_score']} for row in result['results']], key=lambda x: (-x['relevance_score'], x['index']))
    if body.return_documents:
        for row in results:
            row['document'] = {'text': body.documents[row['index']]}
    result['results'] = results[:body.top_n or len(results)]
    return result


@app.post('/v1/rerank', dependencies=[Depends(authorize)])
async def rerank(body: RerankRequest):
    return await execute(body.model, lambda: score(body))


@app.post('/v1/rerank-batch', dependencies=[Depends(authorize)])
async def rerank_batch(body: PairBatchRequest):
    if any(q < 0 or q >= len(body.queries) or d < 0 or d >= len(body.documents) for q, d in body.pairs):
        raise HTTPException(status_code=422, detail='Invalid query/document pair index')
    return await execute(body.model, lambda: score_pairs(body.queries, body.documents, body.pairs, body.instruction, body.max_batch_size))


async def execute(model, function):
    if model not in [MODEL_ID, f'Qwen/{MODEL_ID}']:
        raise HTTPException(status_code=400, detail='Unsupported model')
    if not state['ready']:
        raise HTTPException(status_code=503, detail='Model loading')
    try:
        await asyncio.wait_for(lock.acquire(), timeout=2)
    except TimeoutError:
        raise HTTPException(status_code=429, detail='Reranker busy')
    task = asyncio.create_task(asyncio.to_thread(function))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # A disconnected client must not release the GPU lock while its worker
        # is still running. Finish this bounded job before admitting another.
        try:
            await asyncio.shield(task)
        finally:
            raise
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        raise HTTPException(status_code=503, detail='GPU memory limit; reduce request size')
    except TimeoutError:
        raise HTTPException(status_code=504, detail='Rerank deadline exceeded')
    finally:
        lock.release()
