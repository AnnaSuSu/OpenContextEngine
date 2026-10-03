/** Parse SSE across arbitrary network chunk and UTF-8 boundaries. */
export async function* parseSSE(body) {
  const decoder = new TextDecoder();
  let pending = '';
  let data = [];
  for await (const bytes of body) {
    pending += decoder.decode(bytes, { stream: true });
    let end;
    while ((end = pending.indexOf('\n')) >= 0) {
      const line = pending.slice(0, end).replace(/\r$/, '');
      pending = pending.slice(end + 1);
      if (line === '') {
        if (data.length) yield data.join('\n');
        data = [];
      } else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
    }
  }
  pending += decoder.decode();
  if (pending.replace(/\r$/, '').startsWith('data:')) data.push(pending.slice(5).trimStart());
  if (data.length) yield data.join('\n');
}

export async function responseRequest(config, payload, fetchImpl = fetch) {
  const started = performance.now();
  const response = await fetchImpl(`${config.baseUrl}/responses`, {
    method: 'POST', redirect: 'error', signal: AbortSignal.timeout(config.timeoutMs),
    headers: { Authorization: `Bearer ${config.apiKey}`, 'Content-Type': 'application/json',
      Accept: 'text/event-stream', 'User-Agent': config.userAgent },
    body: JSON.stringify({ model: config.model, reasoning: { effort: config.effort },
      stream: true, store: false, max_output_tokens: 2048, ...payload }),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${(await response.text()).slice(0, 1200)}`);
  if (!response.headers.get('content-type')?.includes('text/event-stream')) {
    throw new Error(`Expected SSE, received ${response.headers.get('content-type')}`);
  }
  const eventCounts = {};
  let completed;
  for await (const data of parseSSE(response.body)) {
    if (data === '[DONE]') continue;
    const event = JSON.parse(data);
    eventCounts[event.type] = (eventCounts[event.type] || 0) + 1;
    if (['error', 'response.failed', 'response.incomplete'].includes(event.type)) {
      throw new Error(`Response failed: ${JSON.stringify(event.error || event.response?.error || event.response?.incomplete_details || event.type)}`);
    }
    if (event.type === 'response.completed') completed = event.response;
  }
  if (completed?.status !== 'completed') throw new Error('SSE ended without a successful response.completed');
  return { response: completed, eventCounts, elapsedMs: Math.round(performance.now() - started) };
}

export async function probe(config, nonce, request = responseRequest) {
  const tools = [{ type: 'function', name: 'read_probe_token',
    description: 'Read a newly generated token from the local test harness.',
    parameters: { type: 'object', properties: {}, required: [], additionalProperties: false }, strict: true }];
  const input = [{ role: 'user', content: 'Call read_probe_token exactly once. After receiving its result, reply with only the exact token.' }];
  const first = await request(config, { input, tools, tool_choice: { type: 'function', name: 'read_probe_token' } });
  const calls = first.response.output.filter(item => item.type === 'function_call');
  if (calls.length !== 1 || calls[0].name !== 'read_probe_token' || !calls[0].call_id) {
    throw new Error('Missing expected function call');
  }
  const second = await request(config, { input: [...input, ...first.response.output,
    { type: 'function_call_output', call_id: calls[0].call_id, output: nonce }], tools, tool_choice: 'none' });
  const answer = second.response.output.flatMap(item => item.content || [])
    .filter(item => item.type === 'output_text').map(item => item.text).join('').trim();
  const passed = answer === nonce;
  return { passed, functionCall: calls[0].name, tokenRoundTrip: passed,
    calls: [first, second].map(r => ({ elapsedMs: r.elapsedMs, eventCounts: r.eventCounts,
      responseModel: r.response.model, usage: r.response.usage, status: r.response.status })) };
}
