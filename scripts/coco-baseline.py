"""Run the unmodified pinned CocoIndex Code indexing/search implementation.

Transport credentials point at the bounded local embedding gateway. The runner
does not load reference answers. It retains native outputs before formatting.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from cocoindex_code.project import Project
from cocoindex_code.settings import EmbeddingSettings, default_project_settings, save_project_settings, project_settings_path
from cocoindex_code.shared import create_embedder


async def main():
    corpus, query_file, output = map(lambda p: Path(p).resolve(), sys.argv[1:4])
    output.mkdir(parents=True, exist_ok=True)
    queries = json.loads(query_file.read_text())
    if not project_settings_path(corpus).exists():
        save_project_settings(corpus, default_project_settings())
    # The gateway owns upstream authentication and strictly limits network use.
    embedder = create_embedder(EmbeddingSettings(
        provider='litellm', model='openai/Qwen3-Embedding-4B', min_interval_ms=0,
    ), {'api_base': os.environ['BASELINE_EMBEDDING_URL'], 'api_key': 'local-only',
        'timeout': 90, 'num_retries': 0})
    project = await Project.create(corpus, embedder, {}, {})
    report = {'system': 'CocoIndex Code', 'status': 'running', 'results': [], 'limit': 60}
    save = lambda: (output / 'native-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    started = time.monotonic()
    last_progress = 0

    def progress(p):
        nonlocal last_progress
        now = time.monotonic()
        if now - last_progress > 15:
            print(json.dumps({'stage': 'indexing', 'progress': str(p)}), flush=True)
            last_progress = now

    try:
        async with asyncio.timeout(5400):
            await project.run_index(on_progress=progress)
        report['indexingMs'] = round((time.monotonic()-started)*1000)
        status = project.get_status()
        report['indexStatus'] = {'files': status.total_files, 'chunks': status.total_chunks, 'indexExists': status.index_exists}
        snapshot = json.loads((query_file.parent/'snapshot.json').read_text())
        expected_files = sum(bool((corpus/f['path']).read_text().strip()) for f in snapshot['files'])
        progress_status = project.indexing_stats
        report['indexStatus']['expectedNonemptyFiles'] = expected_files
        report['indexStatus']['errors'] = progress_status.num_errors if progress_status else None
        if not status.index_exists or status.total_files != expected_files or progress_status and progress_status.num_errors:
            raise RuntimeError('Incomplete index; do not score retrieval from missing input files')
        print(json.dumps({'indexingMs': report['indexingMs'], 'status': report['indexStatus']}), flush=True)
        save()
        for i, case in enumerate(queries['cases']):
            for lang in (['zh','en'] if i % 2 == 0 else ['en','zh']):
                start = time.monotonic()
                async with asyncio.timeout(120):
                    rows = await project.search(case['queries'][lang], limit=60)
                data = [dict(file_path=r.file_path, start_line=r.start_line, end_line=r.end_line,
                             content=r.content, score=r.score, language=r.language) for r in rows]
                native = f"{case['id']}.{lang}.native.json"
                (output / native).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
                result = {'id': case['id'], 'language': lang, 'status': 'completed',
                          'elapsedMs': round((time.monotonic()-start)*1000), 'nativeFile': native}
                report['results'].append(result); save(); print(json.dumps(result), flush=True)
        report['status'] = 'completed'
    except Exception as exc:
        # No upstream secrets exist in this process. Keep a compact exception.
        report['status'] = 'failed'; report['error'] = str(exc)[:1500]
        raise
    finally:
        report['elapsedMs'] = round((time.monotonic()-started)*1000)
        save(); project.close()


if __name__ == '__main__':
    asyncio.run(main())
