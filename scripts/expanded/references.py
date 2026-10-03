"""Source-reviewed spans, fixed before either retrieval system runs."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
ANSWERS={name:[] for name in ['click','httpx','zod']}
def add(repo,task,units):
 result=[]
 for uid,fact,spans in units:
  all_of=[]
  for path,start,end in spans:
   lines=(ROOT/f'.pilot-state/expanded-v1/{repo}/corpus'/path).read_text().splitlines()
   assert 1<=start<=end<=len(lines)
   quote='\n'.join(lines[start-1:end]);all_of.append({'path':path,'startLine':start,'endLine':end,'quote':quote,'sha256':hashlib.sha256(quote.encode()).hexdigest()})
  result.append({'id':uid,'fact':fact,'alternatives':[{'allOf':all_of}]})
 ANSWERS[repo].append({'id':task,'units':result})
C='src/click/core.py';T='src/click/types.py';U='src/click/utils.py';F='src/click/_compat.py';S='src/click/shell_completion.py'
add('click','value-precedence',[
 ('cli-env','命令行值优先，缺失时才读取环境变量。',[(C,2281,2286)]),
 ('defaults','环境变量仍缺失时依次使用默认映射和声明默认值。',[(C,2288,2296)]),
 ('source','解析处理记录所选值的来源并进入值处理。',[(C,2398,2403)])])
add('click','prompt-validation',[
 ('prompt','默认或未设置的值在启用提示且需要输入、非宽容解析时触发交互。',[(C,2962,2969)]),
 ('convert-required','值先转换类型，必填而缺失则抛参数异常。',[(C,2358,2362)]),
 ('callback','存在自定义回调时调用并采用回调返回值。',[(C,2364,2367)])])
add('click','subcommand-dispatch',[
 ('resolve','根据首个参数查找子命令，必要时规范化名称后重试。',[(C,1734,1744)]),
 ('parent','记录被调用子命令并先调用父命令。',[(C,1691,1694)]),
 ('child','为子命令建立带父上下文的上下文并调用它。',[(C,1695,1697)])])
add('click','command-chain',[
 ('parse','循环建立子上下文，把剩余参数交给后续命令。',[(C,1711,1723)]),
 ('ordered','顺序进入子上下文并收集每次调用结果。',[(C,1725,1729)]),
 ('result','结果回调接收收集的值以及父上下文参数。',[(C,1664,1667)])])
add('click','resource-cleanup',[
 ('managed','通过退出栈进入资源上下文管理器。',[(C,585,585)]),
 ('callback','清理回调注册到同一个退出栈。',[(C,597,597)]),
 ('close','最外层上下文退出触发关闭，执行退出栈后重建栈。',[(C,473,476),(C,604,606)])])
add('click','lazy-atomic-file',[
 ('register','延迟文件参数创建包装对象，并将智能关闭登记到上下文。',[(T,718,726)]),
 ('open','延迟包装在需要访问时打开底层流，已有打开的流直接复用。',[(U,140,141),(U,153,158)]),
 ('temporary','原子写在目标目录创建临时文件，并包装为原子文件。',[(F,428,435),(F,449,451)]),
 ('replace','关闭原子文件时先关闭底层文件，再替换目标路径。',[(F,465,470)])])
add('click','path-validation',[
 ('missing','stat 失败时按是否要求存在决定返回还是报错。',[(T,875,880)]),
 ('kind','按文件和目录允许标记拒绝不匹配的路径类型。',[(T,888,889),(T,896,897)]),
 ('permissions','按 readable 和 writable 配置检查访问权限。',[(T,905,906),(T,914,915)])])
add('click','choice-normalization',[
 ('normalize','输入和候选经过上下文规范化，并可同时做 casefold。',[(T,279,291)]),
 ('original','匹配后返回保存的原始候选值。',[(T,293,294)]),
 ('invalid','未匹配时通过参数错误报告输入及可选值。',[(T,296,302)])])
add('click','command-errors',[
 ('interrupt','EOF 或键盘中断转换为 Abort，独立模式输出终止并退出。',[(C,1093,1095),(C,1121,1125)]),
 ('usage','Click 异常在独立模式显示并使用异常退出码，否则向上传播。',[(C,1096,1100)]),
 ('exit','显式退出在独立模式退出进程，否则返回退出码。',[(C,1108,1110),(C,1120,1120)]),
 ('return','非独立运行返回命令调用结果。',[(C,1081,1084)])])
add('click','shell-completion',[
 ('instruction','按 shell 和指令选择实现，分别处理脚本生成与补全。',[(S,36,50)]),
 ('dispatch','解析上下文和待补全部分后调用目标的 shell_complete。',[(S,273,275)]),
 ('target','未完成选项或位置参数优先提供补全，否则交给命令。',[(S,591,603)])])
C='httpx/_client.py';A='httpx/_auth.py';M='httpx/_models.py';P='httpx/_multipart.py';U='httpx/_utils.py';F='httpx/_config.py';E='httpx/_exceptions.py';N='httpx/_content.py'
add('httpx','redirect-security',[
 ('limit','通过历史长度限制重定向次数并构造下一次请求。',[(C,970,974),(C,985,989)]),
 ('method-body','按重定向状态改写方法，变为 GET 时丢弃请求体。',[(C,502,513),(C,579,582)]),
 ('credentials','跨源且不是直接 HTTP 到 HTTPS 跳转时移除认证头。',[(C,552,559)])])
add('httpx','digest-auth',[
 ('challenge','只对带摘要认证挑战的 401 响应继续认证流程。',[(A,199,208),(A,214,219)]),
 ('parse','解析挑战字段并提取 realm、nonce、算法等信息。',[(A,237,250)]),
 ('header','根据凭据、请求方法与路径和挑战计算摘要并返回认证头。',[(A,263,268),(A,278,291),(A,301,301)]),
 ('cookie-retry','将响应 cookie 加入请求并再次提交请求。',[(A,220,222)])])
add('httpx','request-merging',[
 ('url','相对 URL 拼接基础路径，绝对 URL 保持自身。',[(C,396,397),(C,409,411)]),
 ('headers-cookies','复制客户端头和 cookie，再用请求级数据更新。',[(C,418,422),(C,429,431)]),
 ('query-params','复制客户端查询参数并合并请求级参数。',[(C,440,443)])])
add('httpx','response-decoding',[
 ('decompress','根据 Content-Encoding 创建解码器，对原始字节解码并刷新尾部。',[(M,704,711),(M,894,905)]),
 ('text','按响应字符编码把字节转为文本并刷新剩余内容。',[(M,913,924)]),
 ('lines','文本经行解码器逐行输出并在结束时刷新。',[(M,926,933)])])
add('httpx','stream-cleanup',[
 ('context','流式发送后 yield 响应，并在 finally 中关闭。',[(C,868,877)]),
 ('response-close','响应仅关闭一次，标记状态并关闭底层流。',[(M,969,972)]),
 ('timing','包装流关闭时写入耗时，再关闭其底层流。',[(C,156,159)])])
add('httpx','cookie-persistence',[
 ('extract','客户端收到响应后提取 cookie，交由标准 cookie jar 处理。',[(C,1022,1022),(M,1105,1108)]),
 ('merge','构造请求时合并客户端与请求级 cookie，并设置请求头。',[(C,368,368),(C,418,421),(M,403,404)]),
 ('policy','使用 cookie jar 的 add_cookie_header 为目标请求选择适用 cookie。',[(M,1114,1115)])])
add('httpx','multipart-upload',[
 ('boundary','为 multipart 生成边界并写入 Content-Type。',[(P,235,241)]),
 ('fields','表单和文件转换为字段，并按边界逐个序列化。',[(P,247,263)]),
 ('file-data','文件字段输出头部后，分块读取并输出文件内容。',[(P,214,221)]),
 ('length','不能提前计算长度时返回分块传输头，否则给出 Content-Length。',[(P,273,276),(P,287,292)])])
add('httpx','timeout-overrides',[
 ('defaults','未单独设置的超时分量继承默认值，独立设置覆盖默认。',[(F,127,130)]),
 ('request','构建请求时选择客户端超时或请求覆盖值，并保留已提供的 timeout 扩展。',[(C,370,377)]),
 ('transport','四种超时以字典形式传入请求扩展。',[(F,132,138)])])
add('httpx','proxy-bypass',[
 ('environment','启用环境代理时读取系统环境代理并构造映射。',[(C,242,247),(U,37,45)]),
 ('bypass','NO_PROXY 全通配符取消代理，其他主机映射到无代理。',[(U,47,51),(U,56,57),(U,65,74)]),
 ('match','按 scheme、host 和 port 匹配模式，并选择代理或直接传输。',[(U,192,203),(C,765,769)])])
add('httpx','status-errors',[
 ('success','成功状态直接返回响应。',[(M,805,806)]),
 ('messages','重定向可包含目标位置，并按状态类别构建错误消息。',[(M,808,813),(M,820,828)]),
 ('exception','异常保留请求和响应实例。',[(M,829,829),(E,265,268)])])
T='src/types.ts';E='src/ZodError.ts';P='src/helpers/parseUtil.ts'
add('zod','safe-parsing',[
 ('context','不抛异常解析建立 issues、路径、类型和错误映射上下文，再调用解析。',[(T,251,265)]),
 ('result','有效结果返回 success/data，无效结果用收集的 issues 构造错误。',[(T,98,99),(T,105,111)]),
 ('throwing','抛异常入口复用不抛异常解析，成功取数据，失败抛出错误。',[(T,241,245)])])
add('zod','unknown-properties',[
 ('strip','strip 模式不收集额外键，解析时不为额外键添加结果。',[(T,2605,2615),(T,2653,2654)]),
 ('passthrough','passthrough 将额外键及原始值加入结果对。',[(T,2638,2644)]),
 ('strict','strict 将额外键记录为 unrecognized_keys 并标记 dirty。',[(T,2645,2652)])])
add('zod','async-refinement',[
 ('execute','执行 refinement，异步模式将其结果包装为 Promise。',[(T,4679,4684)]),
 ('sync-error','同步模式收到 Promise 时明确报错。',[(T,4685,4689)]),
 ('await','异步先解析内部模式，再等待 refinement，保留解析状态。',[(T,4706,4715)])])
add('zod','tagged-union',[
 ('mapping','从各分支提取标签，拒绝重复值并建立标签到分支的映射。',[(T,3352,3356),(T,3362,3368),(T,3371,3372)]),
 ('select','读取输入标签并查找分支，再按同步或异步模式解析。',[(T,3290,3294),(T,3305,3316)]),
 ('invalid','未找到分支时报告有效标签列表和标签字段路径。',[(T,3296,3302)])])
add('zod','union-failures',[
 ('success','按分支尝试时优先返回第一个 valid 结果。',[(T,3168,3172)]),
 ('dirty','没有 valid 时使用 dirty 分支并合并其 issues。',[(T,3179,3182)]),
 ('errors','全部无效时按各分支 issues 构造联合类型错误。',[(T,3184,3190)])])
add('zod','missing-null-default',[
 ('optional','undefined 被可选包装直接接受，否则调用内部解析。',[(T,4802,4808)]),
 ('nullable','null 被可空包装直接接受，否则调用内部解析。',[(T,4846,4852)]),
 ('default','缺失时求默认值，然后将替换后的值继续交给内部模式。',[(T,4889,4899)])])
add('zod','preprocess-transform',[
 ('preprocess','预处理先对原始输入运行转换，再解析处理后的值。',[(T,4649,4650),(T,4667,4672)]),
 ('status','自定义 issue 可以中止或标脏，预处理和内部解析的状态继续向外传播。',[(T,4633,4640),(T,4673,4676)]),
 ('transform','转换阶段先完成内部解析，仅对有效结果执行转换。',[(T,4719,4729)])])
add('zod','nested-errors',[
 ('path','构造 issue 时合并上下文路径和自定义路径，再存入公共问题列表。',[(P,12,17),(P,77,80),(P,88,88)]),
 ('tree','错误格式化沿路径建立嵌套节点并在末端添加错误。',[(E,241,248),(E,256,263)]),
 ('flat','扁平格式按路径首元素分组，无路径错误进入表单错误列表。',[(E,307,317)])])
add('zod','partial-required',[
 ('partial','按掩码保留未选字段，选中的字段添加 optional 包装。',[(T,2963,2971)]),
 ('required','按掩码选择字段并循环移除 optional 包装。',[(T,2996,3008)]),
 ('deep','嵌套对象字段递归可选化，数组递归处理元素类型。',[(T,2543,2558)])])
add('zod','intersection-merging',[
 ('objects','两侧对象的公共字段递归合并，冲突会返回无效。',[(T,3414,3429)]),
 ('arrays','数组要求长度一致，并逐项递归合并。',[(T,3430,3445)]),
 ('status','任一侧中止则失败，dirty 状态传播到最终结果。',[(T,3474,3476),(T,3487,3491)]),
 ('conflict','两侧值合并失败时报告交叉类型错误。',[(T,3478,3484)])])
# Equivalent sync/async implementation paths are frozen before outputs are seen.
def alternate(repo,task,unit,spans):
 target=next(u for a in ANSWERS[repo] if a['id']==task for u in a['units'] if u['id']==unit)
 all_of=[]
 for path,start,end in spans:
  lines=(ROOT/f'.pilot-state/expanded-v1/{repo}/corpus'/path).read_text().splitlines();quote='\n'.join(lines[start-1:end])
  all_of.append({'path':path,'startLine':start,'endLine':end,'quote':quote,'sha256':hashlib.sha256(quote.encode()).hexdigest()})
 target['alternatives'].append({'allOf':all_of})
alternate('zod','union-failures','success',[(T,3101,3105)])
alternate('zod','union-failures','dirty',[(T,3107,3113)])
alternate('zod','union-failures','errors',[(T,3117,3125)])
alternate('zod','preprocess-transform','preprocess',[(T,4649,4650),(T,4652,4660)])
alternate('zod','preprocess-transform','status',[(T,4633,4640),(T,4661,4664)])
alternate('zod','preprocess-transform','transform',[(T,4719,4719),(T,4738,4745)])
for repo,answers in ANSWERS.items():
 base=ROOT/f'eval/expanded-v1/{repo}';snapshot=json.loads((base/'snapshot.json').read_text());queries=json.loads((base/'queries.json').read_text())
 assert [a['id'] for a in answers]==[q['id'] for q in queries['cases']]
 data={'schemaVersion':1,'dataset':queries['dataset'],'answerVersion':'v1','repository':snapshot['repository'],'commit':snapshot['commit'],
 'annotator':'Codex reading the frozen source before any retrieval output','status':'source-reviewed; not human or independent multi-annotator ground truth',
 'coverageRule':'Any alternative may satisfy a unit; all exact source lines in that alternative are required.','answers':answers}
 (base/'answers.v1.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
 print(repo,len(answers),'tasks',sum(len(a['units']) for a in answers),'evidence units')
