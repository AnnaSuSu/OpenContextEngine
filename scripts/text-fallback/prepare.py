"""Freeze a small source-derived mixed-language validation before model queries."""
import hashlib,json,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/retrieval'))
from languages.files import discover_snapshot
repo=ROOT/'.pilot-state/text-fallback-v1/repo'
base=ROOT/'eval/text-fallback-v1'
corpus=ROOT/'.pilot-state/text-fallback-v1/corpus'
assert subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()=='e9174d671b1882758cd32ac5e146200f5bee3e45'
if (base/'freeze.json').exists():raise SystemExit('Validation inputs are already frozen; do not overwrite')
snapshot=discover_snapshot(repo)
snapshot.update(repository='evanw/esbuild',tag='v0.25.0',commit='e9174d671b1882758cd32ac5e146200f5bee3e45')
for file in snapshot['files']:
 target=corpus/file['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(repo/file['path'],target)
# Facts are source-derived, not a held-out benchmark. No query output is consulted.
cases=[
 ('boolean-flags','go','找到命令行布尔选项解析代码：未提供等号时怎样使用默认值，显式真假值和无效值怎样处理？','Find command-line boolean option parsing: how are defaults used without an equals sign, and how are explicit true/false and invalid values handled?',
 [('default','Use the default when no equals sign is supplied','pkg/cli/cli_impl.go',66,70),('values','Accept true and false and explain invalid values','pkg/cli/cli_impl.go',71,81)]),
 ('watch-lifetime','go','找到命令行启动文件监视的代码：如何先校验构建选项，以及为什么进程不会马上退出？','Find how the command-line starts file watching: how are build options validated first, and why does the process stay alive?',
 [('validation','Create a context and reject invalid build options','pkg/cli/cli_impl.go',1323,1329),('lifetime','Start watching and block instead of exiting','pkg/cli/cli_impl.go',1331,1334)]),
 ('worker-input-close','javascript','找到打包 WebAssembly worker 时向子进程传入生成代码的脚本：怎样发送输入并显式关闭标准输入以避免挂起？','Find the script that bundles a WebAssembly worker by sending generated code to a child process: how is input sent and standard input explicitly closed to avoid hanging?',
 [('process','Start the asynchronous compiler process and handle completion','scripts/esbuild.js',113,117),('close','Write the generated input and close stdin','scripts/esbuild.js',118,120)]),
 ('optional-platforms','javascript','找到发布 npm 包时生成可选平台依赖的脚本：如何汇总不同操作系统的包名并统一设置版本，再写回包配置？','Find the script that generates optional platform dependencies for an npm release: how are package names across operating systems collected, assigned a common version, and written back?',
 [('platforms','Collect and sort platform packages with the release version','scripts/esbuild.js',76,80),('write','Write optional dependencies to package configuration','scripts/esbuild.js',83,86)]),
 ('sync-worker-reuse','typescript','找到 Node 同步构建入口：怎样复用长期存活的 worker 线程降低启动开销，不可用时走哪条同步路径？','Find the Node synchronous build entry point: how is a long-lived worker thread reused to reduce startup overhead, and what synchronous path is used otherwise?',
 [('worker','Reuse or start the worker service outside the internal worker','lib/npm/node.ts',148,153),('fallback','Run the synchronous service and return its result','lib/npm/node.ts',155,164)]),
 ('release-validation','yaml','找到发布构建验证的工作流配置：哪些事件触发它，在哪个操作系统和 Go 版本上运行什么验证命令？','Find the release-build validation workflow: which events trigger it, and on which OS and Go version does it run which validation command?',
 [('triggers','Version tags and manual dispatch trigger validation','.github/workflows/validate.yml',3,6),('runner','Use the Ubuntu runner','.github/workflows/validate.yml',11,13),('go','Install the pinned Go version','.github/workflows/validate.yml',18,21),('command','Run the build validation make target','.github/workflows/validate.yml',24,26)]),
 ('test-targets','make','找到构建配置中开发测试和完整发布测试的入口：它们如何并发执行，完整测试额外包含哪些类型的检查？','Find the build configuration entries for development tests and full release tests: how do they execute concurrently, and which additional kinds of checks are in the full suite?',
 [('development','Run the common development test targets with six parallel jobs','Makefile',12,16),('release','Add the slower release test targets','Makefile',18,20)]),
 ('binary-download','shell','找到安装脚本：怎样根据操作系统和 CPU 选择可执行文件下载地址，处理不支持的平台，并解压到当前目录？','Find the installation script: how does it choose a binary download URL by OS and CPU, handle unsupported platforms, and extract the executable into the current directory?',
 [('select','Identify the platform and choose a package or reject it','dl.sh',3,17),('extract','Extract and move the executable and remove the archive','dl.sh',19,22)]),
]
queries={'cases':[]};answers={'answers':[]}
for ident,language,zh,en,facts in cases:
 queries['cases'].append({'id':ident,'sourceLanguage':language,'queries':{'zh':zh,'en':en}})
 units=[]
 for uid,fact,name,lo,hi in facts:
  lines=(repo/name).read_text().splitlines();spans=[];start=None
  # New protocol excludes blank-only gaps consistently, before retrieval.
  for line in range(lo,hi+2):
   nonblank=line<=hi and bool(lines[line-1].strip())
   if nonblank and start is None:start=line
   if not nonblank and start is not None:
    quote='\n'.join(lines[start-1:line-1]);spans.append({'path':name,'startLine':start,'endLine':line-1,'quote':quote,'sha256':hashlib.sha256(quote.encode()).hexdigest()});start=None
  units.append({'id':uid,'fact':fact,'alternatives':[{'allOf':spans}]})
 answers['answers'].append({'id':ident,'units':units})
protocol={'kind':'source-derived mixed-language smoke validation; not an independent benchmark',
 'primaryBudgetTokens':4000,'queries':16,'independentTasks':8,'maxRerankedCandidates':80,
 'maxEmbeddingCallsPerQuery':1,'maxRerankerCallsPerQuery':2,'queryCache':False,
 'gold':'Nonblank source spans frozen before querying; references stay local',
 'timing':'Remote worker internal elapsed time; not comparable with prior Mac client latency',
 'models':{'embedding':'Qwen3-Embedding-4B','reranker':'Qwen3-Reranker-4B'}}
for name,data in [('snapshot.json',snapshot),('queries.json',queries),('answers.v1.json',answers),('protocol.json',protocol)]:
 (base/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
shutil.copyfile(repo/'LICENSE.md',base/'ESBUILD_LICENSE.txt')
freeze={'sha256':{name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in ['snapshot.json','queries.json','answers.v1.json','protocol.json']}}
(base/'freeze.json').write_text(json.dumps(freeze,indent=2)+'\n')
print(json.dumps({'files':len(snapshot['files']),'tasks':len(cases),'sourceBytes':sum(f['bytes'] for f in snapshot['files'])}))
