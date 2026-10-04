const readline=require('node:readline');
console.log=(...args)=>console.error(...args);
const {Context,OpenAIEmbedding,MilvusVectorDatabase}=require('/root/reponerve-baselines/upstream/claude-context/packages/core/dist/index.js');
process.env.HYBRID_MODE='true';
(async()=>{
 const lines=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
 let context,corpus;
 for await(const line of lines){
  const input=JSON.parse(line);
  if(!context){
   corpus=input.corpus;
   context=new Context({embedding:new OpenAIEmbedding({model:'Qwen3-Embedding-4B',apiKey:'local-only',baseURL:input.embeddingUrl}),vectorDatabase:new MilvusVectorDatabase({address:input.milvusUrl}),customIgnorePatterns:(input.emptyFiles??[]).map(path=>'/'+path)});
   const index=await context.indexCodebase(corpus,undefined,true);
   if(index.status!=='completed')throw Error('Incomplete index');
   process.stdout.write(JSON.stringify({ready:true,...index})+'\n');
  }else{
   const results=await context.semanticSearch(corpus,input.query,60);
   process.stdout.write(JSON.stringify({results})+'\n');
  }
 }
})().catch(e=>{console.error(e);process.exit(1);});
