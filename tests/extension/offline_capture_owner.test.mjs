import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../../app/static/js/offline_capture.js', import.meta.url), 'utf8');

// Execute the actual browser module against a small asynchronous IndexedDB/fetch
// harness, rather than accepting the presence of security-related source strings.
async function fixture() {
  const rows = [];
  let nextId = 1;
  let token = 'token-a';
  let identity = 'tenant-a';
  let failCapture = false;
  const posts = [];
  const request = (fn) => {
    const req = {};
    queueMicrotask(() => { req.result = fn(); req.onsuccess?.(); });
    return req;
  };
  const store = {
    count: () => request(() => rows.length),
    getAll: () => request(() => structuredClone(rows)),
    add: (row) => request(() => { const id = nextId++; rows.push({ ...row, id }); return id; }),
    delete: (id) => request(() => { const i = rows.findIndex(r => r.id === id); if (i >= 0) rows.splice(i, 1); }),
  };
  globalThis.indexedDB = { open: () => request(() => ({ transaction: () => ({ objectStore: () => store }), close() {} })) };
  globalThis.localStorage = { getItem: () => token };
  Object.defineProperty(globalThis, 'navigator', { value: { onLine: true }, configurable: true });
  globalThis.fetch = async (url, options) => {
    if (url.endsWith('/auth/me')) return { ok: !!identity, json: async () => ({ user_id: identity }) };
    posts.push({ url, options });
    return { ok: !failCapture };
  };
  const mod = await import(`data:text/javascript;base64,${Buffer.from(source + '\n//' + Math.random()).toString('base64')}`);
  return { rows, posts, mod, account: (id, t) => { identity = id; token = t; }, fail: (v) => { failCapture = v; } };
}

test('offline replay keeps A and ownerless records while B remains writable, then replays A only as A', async () => {
  const f = await fixture();
  await f.mod.flushOfflineCaptures(); // establish verified A identity before disconnect
  navigator.onLine = false;
  await f.mod.enqueueOfflineCapture('https://example.test/private-a');
  f.rows.push({ id: 99, url: 'https://example.test/legacy' });
  f.account('tenant-b', 'token-b');
  navigator.onLine = true;
  await f.mod.flushOfflineCaptures();
  assert.equal(f.posts.length, 0, 'account switch must not import A or legacy URLs into B');
  navigator.onLine = false;
  await f.mod.enqueueOfflineCapture('https://example.test/private-b');
  navigator.onLine = true;
  await f.mod.flushOfflineCaptures();
  assert.equal(f.posts.length, 1);
  assert.equal(f.posts[0].options.headers['X-Capture-Owner'], 'tenant-b');
  assert.equal(JSON.parse(f.posts[0].options.body).url, 'https://example.test/private-b');
  assert.equal(f.rows.length, 2);
  f.account('tenant-a', 'new-session-a');
  await f.mod.flushOfflineCaptures();
  assert.equal(f.posts.length, 2);
  assert.equal(f.posts[1].options.headers['X-Capture-Owner'], 'tenant-a');
  assert.deepEqual(f.rows.map(r => r.id), [99]);
});

test('unverified/changed offline identity fails closed; persisted queue has no credentials', async () => {
  const f = await fixture();
  await assert.rejects(f.mod.enqueueOfflineCapture('https://example.test/a'), /Connect and sign in/);
  await f.mod.flushOfflineCaptures();
  f.account('tenant-b', 'token-b');
  await assert.rejects(f.mod.enqueueOfflineCapture('https://example.test/b'), /Connect and sign in/);
  await f.mod.flushOfflineCaptures();
  await f.mod.enqueueOfflineCapture('https://example.test/b');
  assert.deepEqual(Object.keys(f.rows[0]).sort(), ['id', 'queued_at', 'url', 'user_id']);
  assert.equal(JSON.stringify(f.rows).includes('token-b'), false);
});

test('rejected replay remains retryable and overlapping flushes do not duplicate writes', async () => {
  const f = await fixture();
  await f.mod.flushOfflineCaptures();
  await f.mod.enqueueOfflineCapture('https://example.test/a');
  f.fail(true);
  await f.mod.flushOfflineCaptures();
  assert.equal(f.rows.length, 1);
  f.fail(false);
  await Promise.all([f.mod.flushOfflineCaptures(), f.mod.flushOfflineCaptures()]);
  assert.equal(f.posts.length, 2); // one rejected request, one successful retry
  assert.equal(f.rows.length, 0);
});
