"""Freeze new Go/JS source-derived questions before retrieval and prepare both views."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src/retrieval'))
import languages
from languages.files import discover_snapshot

TASKS = {
 'cobra': [
  ('argument-bounds', '找到位置参数数量校验：最少、最多和区间限制如何返回错误，组合校验何时停止？',
   'Find positional argument count validation: how do minimum, maximum and range limits report errors, and when does combined validation stop?',
   [('minimum','args.go',74,80),('maximum','args.go',84,90),('range','args.go',104,110),('combined','args.go',114,122)]),
  ('execution-hooks', '找到命令执行的生命周期：怎样先检查位置参数，再执行继承的前置钩子和命令主体，最后执行后置钩子？',
   'Find the command execution lifecycle: how are positional arguments checked before inherited pre-run hooks, the command action, and post-run hooks?',
   [('arguments','command.go',968,970),('parents','command.go',972,983),('pre','command.go',984,997),('action','command.go',1014,1020),('post','command.go',1021,1041)]),
  ('help-priority', '找到帮助选项的处理路径：解析选项失败怎样处理，用户请求帮助时怎样提前退出执行并显示帮助？',
   'Find help option handling: how are flag parsing failures handled, and how does a help request stop execution early and display help?',
   [('parse','command.go',919,922),('stop','command.go',934,936),('display','command.go',1152,1155)]),
  ('context-inheritance', '找到执行上下文的传递：显式上下文如何设置，没有上下文如何补默认值，子命令如何继承父上下文后执行？',
   'Find execution context propagation: how is an explicit context set, a missing context defaulted, and a parent context inherited before a child command runs?',
   [('explicit','command.go',1078,1081),('default','command.go',1084,1087),('inherit','command.go',1144,1148)]),
 ],
 'commander': [
  ('environment-priority', '找到从环境变量读取选项的代码：什么来源的现有值允许覆盖，带参数选项和布尔选项分别怎样触发事件？',
   'Find option loading from environment variables: which existing value sources may be overridden, and how are events emitted for value-taking and boolean options?',
   [('priority','lib/command.js',1927,1936),('events','lib/command.js',1937,1945)]),
  ('implied-options', '找到隐含选项处理：如何识别用户自定义值，决定哪些选项能触发隐含值，并避免覆盖用户已经设置的值？',
   'Find implied option handling: how are custom values identified, triggering options chosen, and existing user values protected from being overwritten?',
   [('custom','lib/command.js',1958,1963),('trigger','lib/command.js',1964,1973),('write','lib/command.js',1974,1983)]),
  ('parse-reset', '找到重复解析命令行的状态管理：首次怎样保存选项及来源，后续怎样恢复和清空参数，哪种配置禁止再次解析？',
   'Find state management for repeated command-line parsing: how are values and sources saved initially, restored with cleared arguments later, and which configuration forbids parsing again?',
   [('dispatch','lib/command.js',1109,1115),('save','lib/command.js',1123,1132),('guard','lib/command.js',1140,1143),('reset','lib/command.js',1145,1155)]),
  ('conflicting-options', '找到互斥选项检查：怎样排除未设置及默认值，发现冲突组合，以及把检查扩展到父命令？',
   'Find conflicting option checks: how are missing and default values excluded, conflicting combinations detected, and checks extended to parent commands?',
   [('filter','lib/command.js',1677,1683),('conflict','lib/command.js',1685,1696),('parents','lib/command.js',1705,1710)]),
 ],
}
sha = lambda raw: hashlib.sha256(raw).hexdigest()
write = lambda path, value: path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def views(name, corpus, snapshot):
    target = ROOT/'.pilot-state/roadmap-v1/prepared'/name
    target.mkdir(parents=True, exist_ok=True)
    original = dict(languages.EXTENSIONS)
    for variant in ['text', 'structure']:
        try:
            if variant == 'text':
                languages.EXTENSIONS.update({ext: 'text' for ext, lang in original.items() if lang in {'go', 'javascript'}})
            report = {}
            options = {'go': {'mode': 'syntax'}} if variant == 'structure' else None
            units = languages.source_units(corpus, snapshot['files'], language_options=options, report=report)
            write(target/(variant+'-units.json'), {'units': units, 'selection': report,
                'languageAdapters': languages.adapter_manifest(snapshot['files'], options), 'variant': variant})
        finally:
            languages.EXTENSIONS.clear(); languages.EXTENSIONS.update(original)


for name, tasks in TASKS.items():
    corpus = ROOT/'.pilot-state/roadmap-v1'/name
    base = ROOT/'eval/js-go-v1'/name
    base.mkdir(parents=True, exist_ok=True)
    if (base/'freeze.json').exists():
        raise ValueError('Never overwrite frozen references')
    snapshot = discover_snapshot(corpus)
    snapshot.update(repository=('https://github.com/spf13/cobra' if name == 'cobra' else 'https://github.com/tj/commander.js'),
                    commit=subprocess.check_output(['git', '-C', str(corpus), 'rev-parse', 'HEAD'], text=True).strip())
    queries, answers = [], []
    for task, zh, en, facts in tasks:
        queries.append({'id': task, 'queries': {'zh': zh, 'en': en}})
        entries = []
        for fact, path, start, end in facts:
            lines = (corpus/path).read_text().splitlines()
            # Freeze nonempty runs so blank lines cannot dominate span coverage.
            spans, cursor = [], start
            while cursor <= end:
                if not lines[cursor-1].strip(): cursor += 1; continue
                stop = cursor
                while stop < end and lines[stop].strip(): stop += 1
                quote = '\n'.join(lines[cursor-1:stop])
                spans.append({'path': path, 'startLine': cursor, 'endLine': stop, 'quote': quote, 'sha256': sha(quote.encode())})
                cursor = stop+1
            entries.append({'id': fact, 'fact': fact, 'alternatives': [{'allOf': spans}]})
        answers.append({'id': task, 'units': entries})
    write(base/'snapshot.json', snapshot)
    write(base/'queries.json', {'cases': queries})
    write(base/'answers.v1.json', {'answers': answers})
    write(base/'protocol.json', {'budget': 4000, 'kind': 'source-derived paired structural ablation',
        'languages': ['zh', 'en'], 'queryCache': False, 'referencesKeptLocal': True,
        'notAnIndependentBenchmark': True, 'selection': 'all eligible files, no query-specific file filtering'})
    write(base/'freeze.json', {'sha256': {p.name: sha(p.read_bytes()) for p in sorted(base.glob('*.json'))}})
    (base/'LICENSE.txt').write_bytes((corpus/('LICENSE.txt' if name == 'cobra' else 'LICENSE')).read_bytes())
    views(name, corpus, snapshot)
    print(json.dumps({'repository': name, 'files': len(snapshot['files']), 'queries': len(queries)*2}), flush=True)

views('esbuild', ROOT/'.pilot-state/text-fallback-v1/corpus', json.loads((ROOT/'eval/text-fallback-v1/snapshot.json').read_text()))
