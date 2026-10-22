let key = '';
let generation = 0;
const $ = id => document.getElementById(id);
async function refresh() {
  if (!key) return;
  const current = generation;
  const response = await fetch('/v1/status', { headers: { Authorization: 'Bearer ' + key }, cache: 'no-store', signal: AbortSignal.timeout(3000) });
  if (!response.ok) throw Error(response.status === 401 ? 'Check your admin key.' : 'Start the proxy and check its policy.');
  const data = await response.json();
  if (current !== generation || !key) return;
  $('mode').textContent = data.policy.mode.toUpperCase();
  const m = data.metrics;
  $('count').textContent = m ? m.blocked + ' requests blocked' : 'Proxy counters not ready.';
  $('metrics').textContent = m ? ['Requests: ' + m.requests, 'Rule candidates: ' + m.candidates, 'Owned HLS segments removed: ' + m.hls_segments_removed,
    'Errors: ' + m.errors, 'Snapshot age: ' + Math.max(0, Math.floor(Date.now()/1000) - m.updated_at) + 's (written on traffic)'].join('\n') : 'Send a test request through the proxy.';
  $('scope').textContent = ['Inspect: ' + (data.policy.inspect_hosts.join(', ') || '(none)'), 'Bypass: ' + (data.policy.bypass_hosts.join(', ') || '(all non-targets)'),
    'Block rules: ' + data.policy.block_rules.length, 'Owned HLS: ' + (data.policy.owned_hls_hosts.join(', ') || '(none)')].join('\n');
  $('fingerprint').textContent = 'PUBLIC CA / SHA-256\n' + data.ca_sha256;
  $('message').textContent = 'Connected. Policy mode: ' + data.policy.mode + '. No live platform support has been validated.';
}
$('connect').addEventListener('click', async () => { generation++; key = $('key').value.trim(); $('key').value = ''; try { await refresh(); } catch(e) { key = ''; $('message').textContent = e.message; } });
$('disconnect').addEventListener('click', () => { generation++; key = ''; $('mode').textContent = 'DISCONNECTED'; $('count').textContent = 'Waiting for status.'; $('scope').textContent = ''; $('metrics').textContent = ''; $('fingerprint').textContent = ''; $('message').textContent = 'Dashboard disconnected. Server policy is unchanged.'; });
setInterval(() => { refresh().catch(e => { $('message').textContent = e.message; }); }, 3000);
