import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';

export const base = process.env.FUSION_BASE_URL || 'http://127.0.0.1:8765';
export async function snapshot() {
  const response = await fetch(`${base}/api/state`);
  assert.ok(response.ok, `state: ${response.status}`);
  return response.json();
}

export async function post(route, value) {
  if (route === 'action') {
    const s = await snapshot();
    value = { request_id: randomUUID(), server_epoch: s.server_epoch,
      renderer_epoch: s.renderer.renderer_epoch, ...value };
    if ('x' in value || 'y' in value) value = { topology_key: s.renderer.topology_key,
      interaction_key: s.renderer.interaction_key, ...value };
  }
  const response = await fetch(`${base}/api/${route}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  });
  assert.ok(response.ok, `${route}: ${response.status} ${response.ok ? '' : await response.text()}`);
  return response.json();
}

export async function complete(requestId, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const response = await fetch(`${base}/api/actions/${encodeURIComponent(requestId)}`);
    assert.ok(response.ok, `action status: ${response.status}`);
    const record = await response.json();
    if (['completed', 'failed', 'cancelled'].includes(record.status)) {
      assert.equal(record.status, 'completed', JSON.stringify(record));
      return record;
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Action did not complete: ${requestId}`);
}
