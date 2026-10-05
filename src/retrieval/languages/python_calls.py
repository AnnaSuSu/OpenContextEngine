"""Conservative lexical import/call resolution; never infer dynamic receivers."""
import ast


def import_bindings(node, module, package):
    if isinstance(node, ast.Import):
        return {a.asname or a.name.split('.')[0]: a.name if a.asname else a.name.split('.')[0]
                for a in node.names}
    prefix = node.module or ''
    if node.level:
        parts = package.split('.') if package else []
        if node.level > len(parts):
            return {}
        prefix = '.'.join(parts[:len(parts) - node.level + 1] + ([prefix] if prefix else []))
    return {a.asname or a.name: '.'.join(filter(None, [prefix, a.name]))
            for a in node.names if a.name != '*'}


class Bindings(ast.NodeVisitor):
    def __init__(self):
        self.names = set()

    def visit_Name(self, node):
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Import(self, node):
        self.names.update(a.asname or a.name.split('.')[0] for a in node.names)

    def visit_ImportFrom(self, node):
        self.names.update(a.asname or a.name for a in node.names)

    def visit_FunctionDef(self, node):
        self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef
    def visit_Lambda(self, node):
        pass

    def visit_ExceptHandler(self, node):
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)


def bound(body):
    visitor = Bindings()
    for node in body:
        visitor.visit(node)
    return visitor.names


def resolved_links(tree, module, package):
    """Return calls with source positions and scoped, qualified targets.

    Imports under uncertain control flow are not assumed to have executed.
    Function-local names shadow outer bindings even before their assignment.
    """
    calls, references = [], []
    globals_ = {}
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            globals_.update(import_bindings(node, module, package))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            globals_[node.name] = module + '.' + node.name
    # A module-level reassignment makes the runtime binding indeterminate.
    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for name in bound([node]):
                globals_.pop(name, None)

    def expression(node, env):
        if node is None:
            return
        if isinstance(node, ast.Lambda):
            local = env.copy()
            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                local.pop(arg.arg, None)
            for arg in (node.args.vararg, node.args.kwarg):
                if arg:
                    local.pop(arg.arg, None)
            expression(node.body, local)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            local = env.copy()
            for gen in node.generators:
                expression(gen.iter, local)
                for name in bound([gen.target]):
                    local.pop(name, None)
                for condition in gen.ifs:
                    expression(condition, local)
            for field in ('elt', 'key', 'value'):
                expression(getattr(node, field, None), local)
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in env:
            references.append((node.lineno, env[node.id]))
        if isinstance(node, ast.Call):
            pieces = []
            head = node.func
            while isinstance(head, ast.Attribute):
                pieces.insert(0, head.attr)
                head = head.value
            if isinstance(head, ast.Name) and head.id in env:
                calls.append((node.lineno, '.'.join([env[head.id]] + pieces)))
        for child in ast.iter_child_nodes(node):
            expression(child, env)

    def statements(body, env, owner=None, prefix='', class_closure=None):
        for node in body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                env.update(import_bindings(node, module, package))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for item in node.decorator_list + node.args.defaults + [d for d in node.args.kw_defaults if d]:
                    expression(item, env)
                local = (class_closure if owner and class_closure is not None else env).copy()
                for name in bound(node.body):
                    local.pop(name, None)
                for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                    local.pop(arg.arg, None)
                for arg in (node.args.vararg, node.args.kwarg):
                    if arg:
                        local.pop(arg.arg, None)
                args = node.args.posonlyargs + node.args.args
                if owner and args and args[0].arg in {'self', 'cls'} and args[0].arg not in bound(node.body):
                    local[args[0].arg] = owner
                statements(node.body, local, prefix=prefix + node.name + '.')
                env[node.name] = module + '.' + prefix + node.name
            elif isinstance(node, ast.ClassDef):
                for item in node.decorator_list + node.bases:
                    expression(item, env)
                name = module + '.' + prefix + node.name
                # Methods close over the containing function/module, not class locals.
                statements(node.body, env.copy(), owner=name, prefix=prefix + node.name + '.', class_closure=env.copy())
                env[node.name] = name
            elif isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.TryStar, ast.Match)):
                # Visit each branch in an isolated scope; invalidate any names
                # it could write, so uncertain imports cannot leak past it.
                changed = bound([node])
                branch_env = {k: v for k, v in env.items() if k not in changed}
                for field, value in ast.iter_fields(node):
                    if field in {'body', 'orelse', 'finalbody'}:
                        statements(value, branch_env.copy(), owner, prefix, class_closure)
                    elif field == 'handlers':
                        for handler in value:
                            statements(handler.body, branch_env.copy(), owner, prefix, class_closure)
                    elif field == 'cases':
                        for case in value:
                            expression(case.guard, branch_env)
                            statements(case.body, branch_env.copy(), owner, prefix, class_closure)
                    elif isinstance(value, ast.AST):
                        expression(value, env)
                    elif isinstance(value, list):
                        for item in value:
                            if isinstance(item, ast.AST):
                                expression(item, env)
                for name in changed:
                    env.pop(name, None)
            else:
                expression(node, env)
                for name in bound([node]):
                    env.pop(name, None)
    statements(tree.body, globals_.copy())
    return {'calls': calls, 'references_value': references}


def symbol_resolver(modules, symbols):
    """Allow source-root prefixes only when a module suffix is unambiguous."""
    suffixes = {}
    for module in modules:
        parts = module.split('.')
        for i in range(len(parts)):
            suffixes.setdefault('.'.join(parts[i:]), set()).add(module)

    def resolve(target):
        if target in symbols:
            return symbols[target]
        parts = target.split('.')
        for split in range(len(parts) - 1, 0, -1):
            name = '.'.join(parts[:split])
            matches = {name} if name in modules else suffixes.get(name, set())
            if len(matches) == 1:
                qualified = next(iter(matches)) + '.' + '.'.join(parts[split:])
                return symbols.get(qualified, [])
            if matches:
                return []
        return []
    return resolve
