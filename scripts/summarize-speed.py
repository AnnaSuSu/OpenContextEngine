"""Rebuild the frozen 2026-10-03 speed comparison from local run artifacts."""
import hashlib
import json
import math
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
RUNS = {
    'ace': ['ace-django-2026-10-03T09-25-00.710Z'],
    'reference-v1': ['reponerve-django-2026-10-03T12-53-21.093Z'],
    'single-stage': ['reponerve-cascade-django-2026-10-03T13-24-22.142Z'],
    'function-entities': ['reponerve-entity-django-2026-10-03T13-34-18.147Z'],
    'batched-server': ['reponerve-batched-django-2026-10-03T13-44-25.710Z'],
    'batched-mac-32': ['reponerve-service-django-2026-10-03T14-01-40.683Z',
                       'reponerve-service-django-2026-10-03T14-02-46.718Z',
                       'reponerve-service-django-2026-10-03T14-03-52.661Z'],
    'batched-mac-64': ['reponerve-service-django-2026-10-03T14-11-07.269Z',
                       'reponerve-service-django-2026-10-03T14-12-24.744Z',
                       'reponerve-service-django-2026-10-03T14-13-39.425Z'],
}

def stats(values):
    values = sorted(values)
    return dict(count=len(values), min=min(values), p50=statistics.median(values),
                p95=values[math.ceil(.95*len(values))-1], max=max(values), mean=statistics.mean(values))

def read(path):
    return json.loads(path.read_text())

systems = {}
identity = None
for label, names in RUNS.items():
    rounds, elapsed, invalid, max_tokens = [], [], 0, 0
    for name in names:
        path = ROOT/'runs'/name
        report, score = read(path/'report.json'), read(path/'scores.v2.json')
        assert report['status'] == 'completed' and len(report['results']) == 20
        key = (score['commit'], score['answerSha256'], score['primaryBudget'])
        identity = identity or key
        assert key == identity and key[2] == 4000
        times = [row['elapsedMs'] for row in report['results']]
        elapsed.extend(times)
        invalid += sum(len(row['rawScore']['diagnostic']['invalid']) for row in score['rows'])
        max_tokens = max(max_tokens, max(row['rawTokens'] for row in score['rows']))
        rounds.append(dict(run='runs/'+name, timingMs=stats(times), coverage=score['summary']['4000'],
                           reportSha256=hashlib.sha256((path/'report.json').read_bytes()).hexdigest(),
                           scoreSha256=hashlib.sha256((path/'scores.v2.json').read_bytes()).hexdigest(),
                           config=report.get('config')))
    systems[label] = dict(rounds=rounds, timingMs=stats(elapsed),
                          invalidSourceOccurrences=invalid, maxRawTokens=max_tokens)
result = dict(schemaVersion=1, kind='development-pilot-speed-comparison', date='2026-10-03',
              commit=identity[0], referenceSha256=identity[1], primaryBudgetTokens=4000,
              independentTasks=10, pairedQueries=20, chosen='batched-mac-32',
              chosenConfiguration=dict(maxBatchSize=32, batchTokenBudget=8192, queryCache=False),
              medianSpeedupOverV1=systems['reference-v1']['timingMs']['p50']/systems['batched-mac-32']['timingMs']['p50'],
              finalDeployment=read(ROOT/'docs/eval/results/reponerve-speed-final-health-20261003.json'),
              notes=['P95 uses nearest rank; P50 averages the central two values for even samples.',
                     'Three client rounds repeat the same 20 queries, not 60 independent tasks.',
                     'Models and index are warm; each query reruns embedding and neural ranking, with no result cache.',
                     'Original v1 and final client differ in execution batching, persistence and transport; this is not an isolated algorithm ablation.',
                     'The final deployment adds health metadata; recorded run source hashes remain preserved.',
                     'Development queries informed architecture selection; no held-out or cross-repository claim.'],
              systems=systems)
output = ROOT/'docs/eval/results/reponerve-speed-20261003.json'
output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({name:value['timingMs'] for name,value in systems.items()},indent=2))
