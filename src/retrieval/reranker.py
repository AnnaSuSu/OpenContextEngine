"""Normalize ordinary rerank and optional multi-query batch responses.

Only requested pairs are sent. Result indices always refer to the submitted
documents, never their relevance-sorted position in a provider response.
"""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import math


def bounded_integer(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'{name} must be an integer from 1 to {maximum}')
    return value


def checked_rows(data, count):
    rows = data.get('results') if isinstance(data, dict) else None
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError('Incomplete rerank response')
    indexed = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid rerank result')
        index, score = row.get('index'), row.get('relevance_score')
        if type(index) is not int or not 0 <= index < count or index in indexed:
            raise ValueError('Invalid rerank result index')
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid rerank relevance score')
        indexed[index] = row
    return [indexed[i] for i in range(count)]


def rerank_pairs(config, queries, documents, pairs, post):
    api = config.get('api', 'rerank')
    if api not in ('rerank', 'rerank-batch'):
        raise ValueError('Rerank API must be rerank or rerank-batch')
    concurrency = bounded_integer(config.get('concurrency', 2), 'Rerank concurrency', 8)
    limit = bounded_integer(config.get('maxDocuments', 128), 'Rerank document limit', 1024)
    for q, d in pairs:
        if type(q) is not int or type(d) is not int or not 0 <= q < len(queries) or not 0 <= d < len(documents):
            raise ValueError('Invalid requested rerank pair')
    if not pairs:
        return {'results': [], 'meta': {'request_count': 0}}
    url = config['baseUrl'].rstrip('/') + '/' + api
    if api == 'rerank-batch':
        data = post(url, {'model': config['model'], 'queries': queries,
                         'documents': documents, 'pairs': pairs}, config['apiKey'])
        rows = checked_rows(data, len(pairs))
        for row, (q, d) in zip(rows, pairs):
            if (type(row.get('query_index')) is not int or type(row.get('document_index')) is not int
                    or (row['query_index'], row['document_index']) != (q, d)):
                raise ValueError('Invalid neural pair mapping')
        return {**data, 'results': rows, 'meta': {**data.get('meta', {}), 'request_count': 1}}

    grouped = defaultdict(dict)
    for q, d in pairs:
        grouped[q][d] = None
    jobs = [(q, ids[start:start + limit]) for q, group in grouped.items()
            for ids in [list(group)] for start in range(0, len(ids), limit)]

    def request(job):
        q, ids = job
        data = post(url, {'model': config['model'], 'query': queries[q],
                         'documents': [documents[d] for d in ids], 'top_n': len(ids)}, config['apiKey'])
        rows = checked_rows(data, len(ids))
        return {(q, ids[row['index']]): row['relevance_score'] for row in rows}, data

    # Fail the whole wave on any error; never silently drop a query or switch API.
    if len(jobs) == 1:
        responses = [request(jobs[0])]
    else:
        with ThreadPoolExecutor(max_workers=min(concurrency, len(jobs))) as pool:
            responses = list(pool.map(request, jobs))
    scores = {pair: score for mapping, _ in responses for pair, score in mapping.items()}
    def total(section, key):
        values = [data[section].get(key) if isinstance(data.get(section), dict) else None
                  for _, data in responses]
        return sum(values) if all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values) else None
    return {'results': [{'index': i, 'query_index': q, 'document_index': d,
                         'relevance_score': scores[q, d]} for i, (q, d) in enumerate(pairs)],
            'usage': {'input_tokens': total('usage', 'input_tokens')},
            'meta': {'request_count': len(jobs), 'elapsed_ms': total('meta', 'elapsed_ms')}}
