"""Python AST adapter; preserves v1 spans and edges for the frozen baseline.

Name-resolved calls/inheritance remain heuristic (shadowing/dynamic dispatch are
not fully resolved); confidence is a provenance category, not a probability.
"""
import ast
from cancellation import check
import re
from collections import defaultdict
from .schema import SourceSyntaxError
from .python_calls import resolved_links, symbol_resolver

def extract(sources, max_lines=65, options=None):
    if options:
        raise ValueError("Python adapter does not accept language options")
    units, trees, aliases, class_bases = [], {}, {}, {}
    diagnostics = []
    scoped_calls = {}
    for source in sources:
        check()
        path, text = source.path, source.text
        lines = text.splitlines()
        module = path.removesuffix('.py').replace('/', '.')
        if module.endswith('.__init__'):
            module = module[:-9]
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as error:
            diagnostics.append({'path': path, 'language': 'python', 'errorType': type(error).__name__,
                                'line': error.lineno or 1, 'column': error.offset or 1})
            continue
        trees[module] = tree
        package = module if path.endswith('/__init__.py') or path == '__init__.py' else module.rpartition('.')[0]
        scoped_calls[module] = resolved_links(tree, module, package)
        imports = {}
        for n in tree.body:
            if isinstance(n, ast.Import):
                for item in n.names:
                    imports[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
            elif isinstance(n, ast.ImportFrom):
                prefix = n.module or ''
                if n.level:
                    package = module if path.endswith('/__init__.py') else module.rsplit('.', 1)[0]
                    parts = package.split('.')
                    prefix = '.'.join(parts[:len(parts) - n.level + 1] + ([prefix] if prefix else []))
                for item in n.names:
                    imports[item.asname or item.name] = prefix + '.' + item.name
        aliases[module] = imports

        def add(start, end, name, kind, node=None, owner=None):
            if start > end:
                return
            # Prefer statement boundaries; oversized statements are split by line.
            boundaries = sorted({n.lineno for n in ast.walk(node) if isinstance(n, ast.stmt)
                                 and start < n.lineno <= end}) if node else []
            while start <= end:
                stop = min(end, start + max_lines - 1)
                choices = [b - 1 for b in boundaries if start + max_lines // 2 <= b <= stop + 1]
                if stop < end and choices:
                    stop = max(choices)
                snippet = '\n'.join(lines[start - 1:stop])
                if snippet.strip():
                    units.append({'id': len(units), 'path': path, 'module': module, 'name': name,
                        'symbol': module + ('.' + name if name else ''), 'kind': kind, 'owner': owner,
                        'start': start, 'end': stop, 'text': snippet,
                        'calls': [ast.unparse(n.func) for n in ast.walk(node)
                                  if isinstance(n, ast.Call) and start <= n.lineno <= stop] if node else [],
                        'edges': []})
                start = stop + 1

        def definitions(body, prefix='', low=1, high=None, owner=None):
            cursor = low
            for n in body:
                if not isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                start = min([n.lineno] + [d.lineno for d in n.decorator_list])
                add(cursor, start - 1, prefix, 'class-body' if prefix else 'module', owner=owner)
                name = '.'.join(x for x in [prefix, n.name] if x)
                if isinstance(n, ast.ClassDef):
                    class_bases[module + '.' + name] = [ast.unparse(b) for b in n.bases]
                    # Keep class header, attributes and docstring as their own spans.
                    definitions(n.body, name, start, n.end_lineno, module + '.' + name)
                else:
                    add(start, n.end_lineno, name, 'function', n, owner)
                cursor = n.end_lineno + 1
            add(cursor, high if high is not None else len(lines), prefix,
                'class-body' if prefix else 'module', owner=owner)

        definitions(tree.body)

    if diagnostics:
        raise SourceSyntaxError(diagnostics)
    symbols = defaultdict(list)
    for u in units:
        symbols[u['symbol']].append(u['id'])
    resolve = symbol_resolver(set(trees), symbols)
    for u in units:
        targets, relations = [], []

        def relate(ids, kind, confidence, resolution):
            targets.extend(ids)
            relations.extend({'target': target, 'kind': kind, 'confidence': confidence,
                              'resolution': resolution} for target in ids if target != u['id'])
        if u['owner']:
            relate(symbols.get(u['owner'], []), 'member_of', 1.0, 'syntax')
        for kind, links in scoped_calls[u['module']].items():
            for line, target in links:
                if u['start'] <= line <= u['end']:
                    relate(resolve(target), kind, .7, 'scoped-import')
        for reference in re.findall(r':(?:func|meth):`~?([A-Za-z_][\w.]*)`', u['text']):
            targets_ = resolve(reference) or resolve(u['module'] + '.' + reference)
            relate(targets_, 'references_value', .6, 'explicit-doc-reference')
        for base in class_bases.get(u['owner'] or u['symbol'], []):
            pieces = base.split('.')
            target = aliases[u['module']].get(pieces[0], u['module'] + '.' + pieces[0])
            if len(pieces) > 1:
                target += '.' + '.'.join(pieces[1:])
            relate(symbols.get(target, []), 'inherits', .7, 'static-name')
        # A split function's parts form one symbol, preserving continuation links.
        relate(symbols[u['symbol']], 'same_symbol', 1.0, 'syntax')
        u['edges'] = sorted(set(targets) - {u['id']})
        u.update(language='python', scope=u['owner'] or u['module'],
                 relations=sorted({(r['target'], r['kind'], r['confidence'], r['resolution']): r
                                   for r in relations}.values(), key=lambda r: (r['target'], r['kind'])))
    return units
