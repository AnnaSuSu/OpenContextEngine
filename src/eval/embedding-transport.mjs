// Retry transport failures only; never alter inputs, models, or providers.
export async function requestEmbeddingBatch({ url, key, model, texts, onAttempt = () => {}, onRetry = () => {}, fetchImpl = fetch, sleep = ms => new Promise(resolve => setTimeout(resolve, ms)) }) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    onAttempt(attempt);
    let retryable = false;
    try {
      const response = await fetchImpl(url, {
        method: 'POST', redirect: 'error', signal: AbortSignal.timeout(30000),
        headers: { authorization: `Bearer ${key}`, 'content-type': 'application/json' },
        body: JSON.stringify({ model, input: texts, encoding_format: 'float' }),
      });
      if (!response.ok) {
        retryable = [408, 429, 500, 502, 503, 504].includes(response.status);
        await response.body?.cancel();
        throw new Error(`Upstream HTTP ${response.status}`);
      }
      return await response.json();
    } catch (error) {
      retryable ||= error.name === 'TimeoutError' || error.name === 'TypeError' && error.message === 'fetch failed';
      if (!retryable || attempt === 3) throw error;
      const delayMs = 1000 * attempt;
      onRetry({ attempt, reason: error.name, message: String(error.message).split(key).join('[REDACTED]').slice(0, 300), delayMs });
      await sleep(delayMs);
    }
  }
}
