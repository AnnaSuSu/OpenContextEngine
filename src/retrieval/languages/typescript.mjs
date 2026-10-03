/** Parse and bind only the frozen source set. Never emit, execute, or load repo plugins. */
import ts from 'typescript';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const COMPILER_VERSION = '5.9.3';
if (ts.version !== COMPILER_VERSION) throw new Error(`Expected TypeScript ${COMPILER_VERSION}; run npm ci`);
const ROOT = '/reponerve-snapshot';
const absolute = name => path.posix.resolve(ROOT, name);
const slashLines = text => text.replace(/\r\n?/g, '\n').split('\n');

export function extract(files, maxLines = 65, settings = {}) {
  if (!settings || typeof settings !== 'object' || Array.isArray(settings)
      || Object.keys(settings).some(key => !['baseUrl', 'paths'].includes(key))) {
    throw new Error('TypeScript options support only explicit baseUrl and paths');
  }
  if (settings.baseUrl !== undefined && typeof settings.baseUrl !== 'string') throw new Error('baseUrl must be text');
  if (settings.paths !== undefined && (!settings.paths || typeof settings.paths !== 'object' || Array.isArray(settings.paths)
      || Object.values(settings.paths).some(v => !Array.isArray(v) || !v.length || v.some(s => typeof s !== 'string')))) {
    throw new Error('paths must map aliases to nonempty arrays of paths');
  }
  const baseUrl = absolute(settings.baseUrl ?? '.');
  if (baseUrl !== ROOT && !baseUrl.startsWith(ROOT + '/')) throw new Error('baseUrl escapes snapshot');
  const texts = new Map(files.map(file => [absolute(file.path), file.text]));
  const directories = new Set([ROOT]);
  for (const name of texts.keys()) {
    for (let directory = path.posix.dirname(name); directory.startsWith(ROOT); directory = path.posix.dirname(directory)) {
      directories.add(directory);
    }
  }
  const options = { target: ts.ScriptTarget.ESNext, module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler, jsx: ts.JsxEmit.Preserve,
    noEmit: true, noLib: true, skipLibCheck: true, allowImportingTsExtensions: true,
    ...(files.some(f => /\.(?:jsx?|mjs|cjs)$/.test(f.path)) ? { allowJs: true, checkJs: true } : {}),
    experimentalDecorators: true, baseUrl, paths: settings.paths };
  const host = {
    getSourceFile: (name, version) => texts.has(name) ? ts.createSourceFile(name, texts.get(name), version, true) : undefined,
    getDefaultLibFileName: () => '', writeFile: () => { throw new Error('Emit is disabled'); },
    getCurrentDirectory: () => ROOT, getDirectories: () => [],
    fileExists: name => texts.has(name), readFile: name => texts.get(name),
    directoryExists: name => directories.has(name), realpath: name => name,
    getCanonicalFileName: name => name, useCaseSensitiveFileNames: () => true, getNewLine: () => '\n',
  };
  const program = ts.createProgram([...texts.keys()], options, host);
  const errors = program.getSyntacticDiagnostics();
  if (errors.length) {
    throw new Error(errors.slice(0, 5).map(d => {
      const line = d.file.getLineAndCharacterOfPosition(d.start ?? 0).line + 1;
      return `${path.posix.relative(ROOT, d.file.fileName)}:${line}: ${ts.flattenDiagnosticMessageText(d.messageText, ' ')}`;
    }).join('\n'));
  }
  const checker = program.getTypeChecker();
  const units = [], records = new Map(), nodeEntries = new Map();
  const executable = node => Boolean(node && ((ts.isFunctionLike(node) && node.body) || ts.isClassLike(node)));
  const named = node => node.name?.getText() ?? (ts.isConstructorDeclaration(node) ? 'constructor' : 'default');
  const describe = node => {
    if (ts.isClassDeclaration(node)) return ['class-body', named(node)];
    if (ts.isInterfaceDeclaration(node)) return ['interface', named(node)];
    if (ts.isTypeAliasDeclaration(node)) return ['type', named(node)];
    if (ts.isEnumDeclaration(node)) return ['enum', named(node)];
    if (ts.isModuleDeclaration(node)) return ['namespace', named(node)];
    if (ts.isFunctionDeclaration(node)) return ['function', named(node)];
    if (ts.isMethodDeclaration(node) || ts.isMethodSignature(node) || ts.isConstructorDeclaration(node)
        || ts.isGetAccessorDeclaration(node) || ts.isSetAccessorDeclaration(node)) return ['method', named(node)];
    if (ts.isPropertyDeclaration(node) || ts.isPropertySignature(node)) return ['property', named(node)];
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer
        && (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer)
            || ts.isClassExpression(node.initializer))) {
      return [ts.isClassExpression(node.initializer) ? 'class-body' : 'function', named(node)];
    }
    return null;
  };

  for (const file of files) {
    const sf = program.getSourceFile(absolute(file.path));
    const lines = slashLines(file.text);
    // Python splitlines() omits the final empty line; use the same span convention.
    if (lines.at(-1) === '') lines.pop();
    const module = file.path.replace(/\.(?:tsx?|mts|cts|jsx?|mjs|cjs)$/, '');
    // Source citations use physical CR/LF lines, including when JavaScript
    // treats a Unicode separator as a lexical line terminator. Offsets are UTF-16.
    const starts = [0, ...[...file.text.matchAll(/\r\n|\r|\n/g)].map(m => m.index + m[0].length)];
    const lineOf = position => {
      let low = 0, high = starts.length;
      while (low + 1 < high) {
        const middle = (low + high) >>> 1;
        if (starts[middle] <= position) low = middle; else high = middle;
      }
      return low + 1;
    };
    const root = { node: sf, name: '', symbol: module + '::', kind: 'module', start: 1,
      end: lines.length, parent: null, depth: 0, ids: [] };
    const entries = [root], boundaries = new Set();
    nodeEntries.set(sf, root);
    function visit(node, parent) {
      let current = parent;
      const description = describe(node);
      if (description) {
        const [kind, shortName] = description;
        const name = parent.name ? `${parent.name}.${shortName}` : shortName;
        current = { node, name, symbol: module + '::' + name, kind, parent, depth: parent.depth + 1,
          start: lineOf(node.getStart(sf, true)), end: lineOf(Math.max(node.getStart(sf), node.end - 1)), ids: [] };
        entries.push(current); nodeEntries.set(node, current);
        if (ts.isVariableDeclaration(node) && node.initializer) nodeEntries.set(node.initializer, current);
      }
      if (ts.isStatement(node)) boundaries.add(lineOf(node.getStart(sf)));
      ts.forEachChild(node, child => visit(child, current));
    }
    ts.forEachChild(sf, child => visit(child, root));
    const owners = Array(lines.length).fill(root);
    for (const entry of entries.slice(1).sort((a, b) => a.depth - b.depth || a.start - b.start)) {
      // A line-addressed evidence unit cannot separate members from a one-line
      // container. Keep the enclosing declaration's identity for that line.
      if (entry.parent !== root && entry.start === entry.parent.start && entry.end === entry.parent.end) continue;
      for (let i = entry.start - 1; i < entry.end; i++) owners[i] = entry;
    }
    const lineUnits = Array(lines.length).fill(null);
    let start = 1;
    while (start <= lines.length) {
      const owner = owners[start - 1];
      let end = start;
      while (end < lines.length && owners[end] === owner) end++;
      while (start <= end) {
        let stop = Math.min(end, start + maxLines - 1);
        if (stop < end) {
          const candidates = [...boundaries].filter(b => start + Math.floor(maxLines / 2) <= b && b <= stop + 1 && b > start);
          if (candidates.length) stop = Math.max(...candidates) - 1;
        }
        const text = lines.slice(start - 1, stop).join('\n');
        if (text.trim()) {
          const id = units.length;
          const unit = { id, language: /\.(?:jsx?|mjs|cjs)$/.test(file.path) ? 'javascript' : 'typescript', path: file.path, module, name: owner.name,
            symbol: owner.symbol, kind: owner.kind, scope: owner.parent?.symbol ?? root.symbol,
            owner: owner.parent && owner.parent !== root ? owner.parent.symbol : null,
            start, end: stop, text, calls: [], relations: [], edges: [], unresolved: [] };
          units.push(unit); owner.ids.push(id);
          for (let i = start - 1; i < stop; i++) lineUnits[i] = id;
        }
        start = stop + 1;
      }
    }
    records.set(sf.fileName, { sf, entries, root, lineUnits, lineOf });
  }
  const unitAt = node => {
    const record = records.get(node.getSourceFile().fileName);
    return record?.lineUnits[record.lineOf(node.getStart()) - 1];
  };
  const entryFor = node => {
    for (let cursor = node; cursor; cursor = cursor.parent) if (nodeEntries.has(cursor)) return nodeEntries.get(cursor);
    return undefined;
  };
  const idsFor = node => {
    if (!records.has(node.getSourceFile().fileName)) return [];
    const entry = entryFor(node);
    // Multiple declarations can share a line. Link to that actual source unit
    // instead of inventing overlapping spans or dropping the declaration.
    return entry?.ids.length ? entry.ids : [unitAt(node)].filter(id => id !== null && id !== undefined);
  };
  const symbolAt = node => {
    let symbol = checker.getSymbolAtLocation(node);
    if (symbol?.flags & ts.SymbolFlags.Alias) symbol = checker.getAliasedSymbol(symbol);
    return symbol;
  };
  const declarations = node => symbolAt(node)?.declarations ?? [];
  const add = (from, targets, kind, confidence, resolution) => {
    if (from === null || from === undefined) return;
    for (const target of targets) if (target !== from) units[from].relations.push({ target, kind, confidence, resolution });
  };
  const unresolved = (node, kind, reason) => {
    const id = unitAt(node);
    if (id !== null && id !== undefined) units[id].unresolved.push({ kind, text: node.getText().slice(0, 200),
      line: records.get(node.getSourceFile().fileName).lineOf(node.getStart()), reason });
  };
  for (const record of records.values()) {
    for (const entry of record.entries) {
      for (const id of entry.ids) {
        add(id, entry.ids, 'same_symbol', 1, 'syntax');
        if (entry.parent && entry.parent !== record.root) add(id, idsFor(entry.parent.node), 'member_of', 1, 'syntax');
      }
    }
    function link(node) {
      if (ts.isCallExpression(node) || ts.isNewExpression(node)) {
        const expression = node.expression;
        const id = unitAt(expression);
        if (id !== null && id !== undefined) units[id].calls.push(expression.getText());
        const type = checker.getTypeAtLocation(expression);
        let targets = [];
        if (!(type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown))) {
          const symbolNode = ts.isPropertyAccessExpression(expression) ? expression.name : expression;
          targets = declarations(symbolNode).filter(executable);
          const signature = checker.getResolvedSignature(node)?.declaration;
          if (!targets.length && executable(signature)) targets = [signature];
        }
        const ids = targets.flatMap(idsFor);
        if (ids.length) add(id, ids, 'calls', .9, 'compiler-symbol');
        else unresolved(expression, 'calls', 'dynamic, external, or no implementation in snapshot');
      }
      if ((ts.isClassLike(node) || ts.isInterfaceDeclaration(node)) && node.heritageClauses) {
        for (const clause of node.heritageClauses) for (const type of clause.types) {
          const targets = declarations(type.expression).flatMap(idsFor);
          const kind = clause.token === ts.SyntaxKind.ExtendsKeyword ? 'inherits' : 'implements';
          for (const id of idsFor(node)) add(id, targets, kind, .9, 'compiler-symbol');
          if (!targets.length) unresolved(type, kind, 'no declaration in snapshot');
        }
      }
      if (ts.isImportClause(node) || ts.isImportSpecifier(node) || ts.isNamespaceImport(node)) {
        if (node.name) {
          const targets = declarations(node.name).flatMap(idsFor);
          add(unitAt(node), targets, 'imports', 1, 'compiler-symbol');
          if (!targets.length) unresolved(node, 'imports', 'external or unresolved module');
        }
      }
      if (ts.isTypeReferenceNode(node)) add(unitAt(node), declarations(node.typeName).flatMap(idsFor), 'references_type', .9, 'compiler-symbol');
      ts.forEachChild(node, link);
    }
    link(record.sf);
  }
  for (const unit of units) {
    unit.relations = [...new Map(unit.relations.map(r => [r.target + ':' + r.kind, r])).values()]
      .sort((a, b) => a.target - b.target || a.kind.localeCompare(b.kind, 'en'));
    unit.edges = [...new Set(unit.relations.map(r => r.target))].sort((a, b) => a - b);
  }
  return { compilerVersion: ts.version, units };
}

if (process.argv[1] && new URL(import.meta.url).pathname === path.resolve(process.argv[1])) {
  try {
    const input = JSON.parse(readFileSync(0, 'utf8'));
    process.stdout.write(JSON.stringify(extract(input.files, input.maxLines, input.options)));
  } catch (error) {
    console.error(error.message); process.exitCode = 1;
  }
}
