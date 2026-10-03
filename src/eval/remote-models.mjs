import os from 'node:os';

// User requirement: model inference must run on a separately authorized server.
export function remoteModelUrl(value) {
  const url = new URL(value);
  const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, '');
  const local = new Set(['localhost', 'localhost.localdomain', '0.0.0.0', '::', '::1', os.hostname().toLowerCase()]);
  for (const addresses of Object.values(os.networkInterfaces())) {
    for (const address of addresses ?? []) local.add(address.address.toLowerCase());
  }
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash ||
      local.has(host) || /^127\./.test(host) || host.endsWith('.localhost') || host.endsWith('.local')) {
    throw new Error('Model endpoint must be remote HTTPS; local model inference is prohibited');
  }
  return url.href.replace(/\/$/, '');
}

export function remoteRerankerConfig(env) {
  if (!env.RERANK_BASE_URL || !env.RERANK_MODEL || !env.RERANK_API_KEY) {
    throw new Error('A user-approved remote reranker is required. No local model will be installed or started.');
  }
  return { baseUrl: remoteModelUrl(env.RERANK_BASE_URL), model: env.RERANK_MODEL, apiKey: env.RERANK_API_KEY };
}

// An explicitly named authorized Linux worker can reach its own remote GPU
// service without a round trip through the public HTTPS proxy. This does not
// permit launching a model process, nor accepting a loopback model on the Mac.
export function rerankerExecutionTransport(env, host = { platform: process.platform, hostname: os.hostname() }) {
  const baseUrl = remoteModelUrl(env.RERANK_BASE_URL);
  if (!env.RERANK_REMOTE_RUNTIME_URL) return { baseUrl, requestBaseUrl: baseUrl, transport: 'https' };
  const url = new URL(env.RERANK_REMOTE_RUNTIME_URL);
  if (host.platform !== 'linux' || env.RERANK_REMOTE_HOST !== host.hostname ||
      url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port ||
      url.pathname !== '/v1' || url.username || url.password || url.search || url.hash) {
    throw new Error('Direct GPU transport requires the explicitly named remote Linux execution host');
  }
  return { baseUrl, requestBaseUrl: url.href, transport: 'authorized-remote-host-loopback', executionHost: host.hostname };
}

// Explicit SSH forwarding reaches a remote service; no local model is loaded.
// Cache identity remains the logical provider URL when transport changes.
export function embeddingTransportConfig(env) {
  const baseUrl = remoteModelUrl(env.EMBEDDING_BASE_URL);
  if (!env.EMBEDDING_SSH_TUNNEL_URL) return { baseUrl, requestBaseUrl: baseUrl, transport: 'https' };
  const tunnel = new URL(env.EMBEDDING_SSH_TUNNEL_URL);
  if (tunnel.protocol !== 'http:' || tunnel.hostname !== '127.0.0.1' || !tunnel.port ||
      tunnel.username || tunnel.password || tunnel.search || tunnel.hash || tunnel.pathname !== '/v1' ||
      !env.EMBEDDING_SSH_REMOTE || !/^[a-zA-Z0-9_.-]+@[a-zA-Z0-9.-]+:[0-9]+$/.test(env.EMBEDDING_SSH_REMOTE)) {
    throw new Error('SSH model transport requires an explicit loopback forward and remote SSH authority');
  }
  return { baseUrl, requestBaseUrl: tunnel.href, transport: 'ssh-tunnel', remote: env.EMBEDDING_SSH_REMOTE };
}
