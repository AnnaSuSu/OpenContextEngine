"""Freeze public source corpora and natural-language tasks before retrieval."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DATA={
'click':('pallets/click','8.1.8','src/click','python',[
('value-precedence','configuration','找到命令选项值来源的处理代码：命令行、环境变量、默认值映射和声明默认值如何确定优先顺序？最后如何记录来源？','Find how command option values are obtained: how are command-line input, environment variables, a defaults mapping, and declared defaults prioritized? How is the chosen source recorded?'),
('prompt-validation','input-validation','找到缺少命令选项时交互提示的处理代码：什么时候询问用户？输入如何转换类型、检查必填项并调用校验回调？','Find interactive prompting for missing command options: when is the user prompted? How is the value converted, checked for required input, and passed to a validation callback?'),
('subcommand-dispatch','cross-file-flow','找到子命令分发代码：如何从剩余参数找到子命令，为它创建子上下文，再调用父命令和子命令？','Find subcommand dispatch: how is a subcommand resolved from the remaining arguments, given a child context, and invoked after the parent command?'),
('command-chain','control-flow','找到连续执行多个子命令的处理代码：如何解析后续子命令，按顺序执行，并将所有结果交给结果回调？','Find chained subcommand execution: how are subsequent commands parsed and invoked in order, and how are their collected results passed to the result callback?'),
('resource-cleanup','resource-lifecycle','找到命令上下文管理资源的代码：如何注册上下文管理器和清理回调？命令退出时如何执行清理？','Find resource management in command contexts: how are context managers and cleanup callbacks registered, and how is cleanup triggered when the command exits?'),
('lazy-atomic-file','cross-file-flow','找到文件参数延迟打开和原子写入的处理代码：何时真正打开文件，如何登记关闭操作，写入何时替换目标文件？','Find lazy opening and atomic writing for file parameters: when is the file actually opened, how is closing registered, and when does a write replace the destination file?'),
('path-validation','input-validation','找到路径参数校验的代码：如何处理路径不存在、文件与目录类型限制，以及可读可写权限？','Find path argument validation: how are missing paths, file-versus-directory restrictions, and readable or writable permissions handled?'),
('choice-normalization','input-validation','找到枚举选项忽略大小写的处理代码：怎样规范化输入和候选值，返回原始候选值，并报告无效输入？','Find case-insensitive choice handling: how are input and choices normalized, how is the original choice returned, and how is invalid input reported?'),
('command-errors','error-handling','找到命令入口的异常处理代码：用户中断、参数错误和正常退出分别怎样转换成终端输出与退出状态？非独立运行模式有什么不同？','Find exception handling at the command entry point: how are user interrupts, usage errors, and normal exits converted into terminal output and exit status? What changes outside standalone mode?'),
('shell-completion','cross-file-flow','找到 shell 补全请求的处理代码：如何识别补全指令、定位当前命令或参数，再调用对应的补全逻辑？','Find shell completion handling: how is a completion instruction recognized, how is the active command or parameter resolved, and how is its completion logic called?'),
]),
'httpx':('encode/httpx','0.28.1','httpx','python',[
('redirect-security','cross-file-flow','找到同步客户端处理重定向的代码：怎样限制跳转次数，改写请求方法和请求体，并避免把认证信息泄露到其他站点？','Find redirect handling in the synchronous client: how are redirect counts limited, methods and request bodies rewritten, and credentials kept from leaking to another site?'),
('digest-auth','authentication','找到摘要认证收到服务器挑战后重试请求的代码：如何解析挑战、构造认证头，并处理服务器设置的 cookie？','Find digest authentication retries after a server challenge: how is the challenge parsed, the authorization header built, and any server-set cookie handled?'),
('request-merging','configuration','找到客户端构造请求的代码：相对地址如何与基础地址合并？请求级的查询参数、头和 cookie 如何与客户端默认值合并？','Find client request construction: how is a relative address merged with the base URL, and how are per-request query parameters, headers, and cookies combined with client defaults?'),
('response-decoding','cross-file-flow','找到同步流式响应解码的代码：压缩后的字节如何解压、转换成文本并按行输出？流结束时如何处理解码器剩余内容？','Find synchronous streaming response decoding: how are compressed bytes decompressed, converted to text, and yielded as lines? How is buffered decoder output flushed at the end?'),
('stream-cleanup','resource-lifecycle','找到同步客户端流式请求的资源清理代码：进入和退出流式上下文时做什么，关闭响应如何关闭底层流并记录耗时？','Find cleanup for synchronous streaming requests: what happens when entering and leaving the streaming context, and how does closing a response close the underlying stream and record elapsed time?'),
('cookie-persistence','cross-file-flow','找到同步客户端接收和发送 cookie 的代码：响应中的 cookie 如何保存到客户端，后续请求又怎样带上符合域名和路径规则的 cookie？','Find cookie persistence in the synchronous client: how are response cookies stored, and how do later requests receive cookies subject to domain and path rules?'),
('multipart-upload','cross-file-flow','找到 multipart 文件上传的编码代码：如何生成分隔符、序列化表单和文件字段，并决定使用内容长度还是分块传输？','Find multipart file upload encoding: how are boundaries generated, form and file fields serialized, and content length or chunked transfer selected?'),
('timeout-overrides','configuration','找到请求超时配置的处理代码：一个默认值怎样展开为连接、读取、写入和连接池等待超时？请求级设置怎样覆盖客户端设置？','Find request timeout configuration: how does one default expand into connect, read, write, and pool timeouts, and how do request-level settings override client settings?'),
('proxy-bypass','configuration','找到同步客户端使用环境代理和绕过代理的代码：如何读取环境设置，匹配无需代理的地址，并为请求选出传输实现？','Find environment proxy and proxy-bypass handling in the synchronous client: how are environment settings read, bypass addresses matched, and a transport selected for a request?'),
('status-errors','error-handling','找到响应状态转成异常的代码：什么情况下不报错，重定向与客户端或服务器错误怎样生成不同消息，异常如何保留请求和响应？','Find conversion of response status into exceptions: when is no error raised, how do redirect and client/server errors get different messages, and how does the exception retain the request and response?'),
]),
'zod':('colinhacks/zod','v3.24.2','src','typescript',[
('safe-parsing','error-handling','找到校验输入时返回成功或失败结果的代码：解析上下文怎样建立，错误怎样汇总，抛异常接口与不抛异常接口如何衔接？','Find validation that returns success or failure: how is the parse context created, how are issues collected, and how do throwing and non-throwing entry points relate?'),
('unknown-properties','input-validation','找到对象包含未声明属性时的处理代码：默认丢弃、允许保留和严格报错三种模式怎样影响最终结果？','Find handling of undeclared object properties: how do default stripping, allowing extra properties, and strict rejection affect the parsed result?'),
('async-refinement','control-flow','找到异步自定义校验的执行代码：异步解析如何等待校验结果，同步解析遇到返回 Promise 的校验时如何处理？','Find execution of asynchronous custom validation: how does async parsing await refinements, and what happens when synchronous parsing encounters a refinement that returns a Promise?'),
('tagged-union','input-validation','找到根据对象标签选择联合类型分支的代码：如何建立标签映射，选择对应分支，并报告无效标签值？','Find selection of a union branch by an object tag: how is the tag mapping built, the matching branch selected, and an invalid tag value reported?'),
('union-failures','error-handling','找到普通联合类型尝试多个候选的代码：怎样优先返回成功分支，在只有部分有效或全部失败时怎样选择结果和汇总错误？','Find ordinary union validation across multiple alternatives: how is a successful branch preferred, and how are results and errors selected when only partial validation succeeds or all branches fail?'),
('missing-null-default','input-validation','找到缺失值、空值和默认值包装的处理代码：允许缺失、允许 null 与提供默认值分别何时直接返回，何时继续调用内部校验？','Find wrappers for missing values, nulls, and defaults: when do optional, nullable, and defaulted values return directly, and when do they continue into inner validation?'),
('preprocess-transform','control-flow','找到预处理和转换组成校验流程的代码：预处理何时运行，失败状态如何传播，转换为什么只在前面的校验成功后执行？','Find validation pipelines with preprocessing and transformation: when does preprocessing run, how does failure status propagate, and why does transformation run only after earlier validation succeeds?'),
('nested-errors','cross-file-flow','找到嵌套字段错误组织成结果的代码：字段路径怎样附加到错误上，怎样得到嵌套错误树和按顶层字段分组的扁平结果？','Find organization of nested field errors: how are field paths attached to issues, and how are a nested error tree and a flat grouping by top-level field produced?'),
('partial-required','schema-construction','找到对象字段变成可选或必填的代码：如何按掩码处理指定字段，移除可选包装，以及递归处理嵌套对象和数组的可选化？','Find making object fields optional or required: how are selected fields handled by a mask, optional wrappers removed, and nested objects and arrays recursively made partial?'),
('intersection-merging','input-validation','找到交叉类型合并两边校验结果的代码：对象和数组怎样递归合并，两边状态如何影响结果，冲突时怎样报告错误？','Find merging of intersection validation results: how are objects and arrays recursively merged, how do the two parse statuses affect the result, and how are conflicts reported?'),
])}
for name,(repo,tag,source,language,tasks) in DATA.items():
 checkout=ROOT/'.pilot-state/expanded-v1/repos'/name;dest=ROOT/f'.pilot-state/expanded-v1/{name}/corpus';base=ROOT/f'eval/expanded-v1/{name}';base.mkdir(parents=True,exist_ok=True)
 commit=subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
 paths=sorted(p for p in (checkout/source).rglob('*') if p.is_file() and p.suffix in (['.py'] if language=='python' else ['.ts','.tsx']) and not {'__tests__','benchmarks','tests','examples'} & set(p.relative_to(checkout).parts))
 files=[]
 for path in paths:
  rel=path.relative_to(checkout).as_posix();raw=path.read_bytes();target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
  files.append({'path':rel,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
 snapshot={'schemaVersion':1,'repository':repo,'tag':tag,'commit':commit,'language':language,'scope':f'{source}/ production source; no tests, benchmarks, examples, docs or dependencies','files':files}
 queries={'schemaVersion':1,'dataset':f'{name}-semantic-expanded-v1','commit':commit,'cases':[{'id':tid,'category':category,'queries':{'zh':zh,'en':en}} for tid,category,zh,en in tasks]}
 for filename,obj in [('snapshot.json',snapshot),('queries.json',queries)]: (base/filename).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'repository':name,'commit':commit,'files':len(files),'bytes':sum(f['bytes'] for f in files),'tasks':len(tasks)}))
