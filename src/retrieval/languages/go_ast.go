// Read only supplied source strings. Never load modules, run source or emit code.
package main

import (
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path"
	"runtime"
	"sort"
	"strings"
)

type Source struct {
	Path string `json:"path"`
	Text string `json:"text"`
}
type Input struct {
	Files   []Source `json:"files"`
	Options Settings `json:"options"`
}
type Settings struct {
	Mode       string `json:"mode"`
	ModulePath string `json:"modulePath"`
	GOOS       string `json:"goos"`
	GOARCH     string `json:"goarch"`
}
type Entry struct {
	Name  string `json:"name"`
	Kind  string `json:"kind"`
	Start int    `json:"start"`
	End   int    `json:"end"`
	Decl  int    `json:"decl"`
}
type Call struct {
	Line       int    `json:"line"`
	Text       string `json:"text"`
	Path       string `json:"targetPath,omitempty"`
	Decl       int    `json:"targetLine,omitempty"`
	Resolution string `json:"resolution,omitempty"`
}
type File struct {
	Path        string   `json:"path"`
	Package     string   `json:"package"`
	Entries     []Entry  `json:"entries"`
	Boundaries  []int    `json:"boundaries"`
	Calls       []Call   `json:"calls"`
	References  []Call   `json:"references"`
	Diagnostics []string `json:"diagnostics"`
	Semantic    bool     `json:"semantic"`
}
type Target struct {
	path string
	line int
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func run() error {
	var input Input
	if err := json.NewDecoder(os.Stdin).Decode(&input); err != nil {
		return err
	}
	fset := token.NewFileSet()
	trees := map[string]*ast.File{}
	texts := map[string]string{}
	objects := map[*ast.Object]Target{}
	functions := map[string][]Target{}
	line := func(p token.Pos) int { return fset.PositionFor(p, false).Line }
	for _, src := range input.Files {
		text := strings.ReplaceAll(strings.ReplaceAll(src.Text, "\r\n", "\n"), "\r", "\n")
		tree, err := parser.ParseFile(fset, src.Path, text, parser.ParseComments|parser.AllErrors)
		if err != nil {
			return err
		}
		trees[src.Path] = tree
		texts[src.Path] = text
		for _, decl := range tree.Decls {
			if fn, ok := decl.(*ast.FuncDecl); ok && fn.Recv == nil {
				t := Target{src.Path, line(fn.Pos())}
				if fn.Name.Obj != nil {
					objects[fn.Name.Obj] = t
				}
				key := path.Dir(src.Path) + "::" + tree.Name.Name + "::" + fn.Name.Name
				functions[key] = append(functions[key], t)
			}
		}
	}
	var typed TypeEvidence
	if input.Options.Mode == "types" {
		typed = resolveTypes(fset, trees, texts, input.Options.ModulePath, input.Options.GOOS, input.Options.GOARCH)
	}
	files := []File{}
	for _, src := range input.Files {
		tree := trees[src.Path]
		out := File{Path: src.Path, Package: tree.Name.Name, Entries: []Entry{}, Boundaries: []int{}, Calls: []Call{}, References: []Call{}, Diagnostics: []string{}}
		if input.Options.Mode == "types" {
			out.Semantic = typed.Selected[src.Path]
			out.Diagnostics = append(out.Diagnostics, typed.Diagnostics[src.Path]...)
		}
		add := func(node ast.Node, name, kind string, doc *ast.CommentGroup) {
			start := line(node.Pos())
			if doc != nil {
				start = line(doc.Pos())
			}
			out.Entries = append(out.Entries, Entry{name, kind, start, line(node.End() - 1), line(node.Pos())})
		}
		for _, decl := range tree.Decls {
			switch d := decl.(type) {
			case *ast.FuncDecl:
				name, kind := d.Name.Name, "function"
				if d.Recv != nil && len(d.Recv.List) > 0 {
					receiver := d.Recv.List[0].Type
					if pointer, ok := receiver.(*ast.StarExpr); ok {
						receiver = pointer.X
					}
					if indexed, ok := receiver.(*ast.IndexExpr); ok {
						receiver = indexed.X
					}
					if indexed, ok := receiver.(*ast.IndexListExpr); ok {
						receiver = indexed.X
					}
					if id, ok := receiver.(*ast.Ident); ok {
						name = id.Name + "." + name
					}
					kind = "method"
				}
				add(d, name, kind, d.Doc)
			case *ast.GenDecl:
				for _, spec := range d.Specs {
					if t, ok := spec.(*ast.TypeSpec); ok {
						add(t, t.Name.Name, "type", t.Doc)
					}
				}
			}
		}
		ast.Inspect(tree, func(node ast.Node) bool {
			if node == nil {
				return true
			}
			if _, ok := node.(ast.Stmt); ok {
				out.Boundaries = append(out.Boundaries, line(node.Pos()))
			}
			if call, ok := node.(*ast.CallExpr); ok {
				expression := call.Fun
				if generic, ok := expression.(*ast.IndexExpr); ok {
					expression = generic.X
				}
				if generic, ok := expression.(*ast.IndexListExpr); ok {
					expression = generic.X
				}
				start, end := fset.PositionFor(expression.Pos(), false).Offset, fset.PositionFor(expression.End(), false).Offset
				text := texts[src.Path][start:end]
				if len(text) > 200 {
					text = text[:200]
				}
				c := Call{Line: line(call.Pos()), Text: text}
				if id, ok := expression.(*ast.Ident); ok {
					var target Target
					if id.Obj != nil {
						target = objects[id.Obj]
					} else {
						candidates := functions[path.Dir(src.Path)+"::"+tree.Name.Name+"::"+id.Name]
						if len(candidates) == 1 {
							target = candidates[0]
						}
					}
					if target.path != "" {
						c.Path = target.path
						c.Decl = target.line
						c.Resolution = "syntax-binding"
					}
				}
				if input.Options.Mode == "types" {
					c.Path = ""
					c.Decl = 0
					c.Resolution = ""
					if target, ok := typed.Calls[call.Pos()]; ok {
						c.Path = target.path
						c.Decl = target.line
						c.Resolution = "compiler-symbol"
					}
				}
				out.Calls = append(out.Calls, c)
			}
			if input.Options.Mode == "types" {
				if target, ok := typed.References[node.Pos()]; ok {
					out.References = append(out.References, Call{Line: line(node.Pos()), Path: target.path, Decl: target.line, Resolution: "compiler-symbol"})
				}
			}
			return true
		})
		sort.Ints(out.Boundaries)
		files = append(files, out)
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"compilerVersion": runtime.Version(), "files": files})
}
