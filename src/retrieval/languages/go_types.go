// Snapshot-only type checking. Missing dependencies remain unresolved; no loader,
// shell command, module download, package initializer or analyzed code is run.
package main

import (
	"fmt"
	"go/ast"
	"go/build"
	"go/token"
	"go/types"
	"io"
	"path"
	"sort"
	"strings"
)

type TypeEvidence struct {
	Calls       map[token.Pos]Target
	References  map[token.Pos]Target
	Diagnostics map[string][]string
	Selected    map[string]bool
}
type snapshotImporter struct {
	fset     *token.FileSet
	files    map[string][]*ast.File
	packages map[string]*types.Package
	visiting map[string]bool
	info     *types.Info
	errors   map[string][]string
	sizes    types.Sizes
	blocked  map[string]bool
}

func (s *snapshotImporter) Import(name string) (*types.Package, error) {
	if p := s.packages[name]; p != nil {
		return p, nil
	}
	files := s.files[name]
	if len(files) == 0 {
		return nil, fmt.Errorf("dependency outside source snapshot: %s", name)
	}
	if s.visiting[name] {
		return nil, fmt.Errorf("snapshot import cycle: %s", name)
	}
	s.visiting[name] = true
	conf := types.Config{Importer: s, DisableUnusedImportCheck: true, Sizes: s.sizes, Error: func(err error) {
		if typed, ok := err.(types.Error); ok {
			pos := s.fset.PositionFor(typed.Pos, false)
			if strings.Contains(typed.Msg, "redeclared") || strings.Contains(typed.Msg, "already declared") {
				s.blocked[name] = true
			}
			if len(s.errors[pos.Filename]) < 20 {
				s.errors[pos.Filename] = append(s.errors[pos.Filename], fmt.Sprintf("%d: %s", pos.Line, typed.Msg))
			}
		}
	}}
	pkg, err := conf.Check(name, s.fset, files, s.info)
	delete(s.visiting, name)
	// go/types returns a partial package on ordinary type errors. Only concrete
	// declarations with positions in this snapshot can become relations later.
	if pkg != nil {
		s.packages[name] = pkg
		return pkg, nil
	}
	return nil, err
}

func resolveTypes(fset *token.FileSet, trees map[string]*ast.File, texts map[string]string,
	modulePath, goos, goarch string) TypeEvidence {
	evidence := TypeEvidence{Calls: map[token.Pos]Target{}, References: map[token.Pos]Target{},
		Diagnostics: map[string][]string{}, Selected: map[string]bool{}}
	context := build.Default
	context.GOOS = goos
	context.GOARCH = goarch
	context.CgoEnabled = false
	context.OpenFile = func(name string) (io.ReadCloser, error) {
		if text, ok := texts[path.Clean(name)]; ok {
			return io.NopCloser(strings.NewReader(text)), nil
		}
		return nil, fmt.Errorf("source outside snapshot: %s", name)
	}
	info := &types.Info{Uses: map[*ast.Ident]types.Object{}, Defs: map[*ast.Ident]types.Object{}, Selections: map[*ast.SelectorExpr]*types.Selection{}}
	loader := &snapshotImporter{fset: fset, files: map[string][]*ast.File{}, packages: map[string]*types.Package{}, visiting: map[string]bool{}, info: info, errors: evidence.Diagnostics, sizes: types.SizesFor("gc", goarch), blocked: map[string]bool{}}
	functions, definitions := map[token.Pos]Target{}, map[token.Pos]Target{}
	names := make([]string, 0, len(trees))
	for name := range trees {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		tree := trees[name]
		// All files remain in the structural index. Semantic links use one explicit
		// build target and exclude external test packages and test-only declarations.
		match, err := context.MatchFile(path.Dir(name), path.Base(name))
		if err != nil {
			evidence.Diagnostics[name] = append(evidence.Diagnostics[name], err.Error())
			continue
		}
		if !match || strings.HasSuffix(name, "_test.go") {
			continue
		}
		evidence.Selected[name] = true
		packagePath := path.Join(modulePath, path.Dir(name))
		loader.files[packagePath] = append(loader.files[packagePath], tree)
		for _, decl := range tree.Decls {
			switch d := decl.(type) {
			case *ast.FuncDecl:
				if d.Body != nil {
					functions[d.Name.Pos()] = Target{name, fset.PositionFor(d.Pos(), false).Line}
				}
			case *ast.GenDecl:
				for _, spec := range d.Specs {
					if t, ok := spec.(*ast.TypeSpec); ok {
						definitions[t.Name.Pos()] = Target{name, fset.PositionFor(t.Pos(), false).Line}
					}
				}
			}
		}
	}
	packageNames := make([]string, 0, len(loader.files))
	for name := range loader.files {
		packageNames = append(packageNames, name)
	}
	sort.Strings(packageNames)
	for _, name := range packageNames {
		_, _ = loader.Import(name)
	}
	for _, name := range names {
		if !evidence.Selected[name] || loader.blocked[path.Join(modulePath, path.Dir(name))] {
			continue
		}
		ast.Inspect(trees[name], func(node ast.Node) bool {
			if call, ok := node.(*ast.CallExpr); ok {
				expression := call.Fun
				if indexed, ok := expression.(*ast.IndexExpr); ok {
					expression = indexed.X
				}
				if indexed, ok := expression.(*ast.IndexListExpr); ok {
					expression = indexed.X
				}
				var object types.Object
				switch x := expression.(type) {
				case *ast.Ident:
					object = info.Uses[x]
				case *ast.SelectorExpr:
					if selection := info.Selections[x]; selection != nil {
						object = selection.Obj()
					} else {
						object = info.Uses[x.Sel]
					}
				}
				if fn, ok := object.(*types.Func); ok {
					if target, found := functions[fn.Pos()]; found && !loader.blocked[path.Join(modulePath, path.Dir(target.path))] {
						evidence.Calls[call.Pos()] = target
					}
				}
			}
			if id, ok := node.(*ast.Ident); ok {
				if object, ok := info.Uses[id].(*types.TypeName); ok {
					if target, found := definitions[object.Pos()]; found && !loader.blocked[path.Join(modulePath, path.Dir(target.path))] {
						evidence.References[id.Pos()] = target
					}
				}
			}
			return true
		})
	}
	return evidence
}
