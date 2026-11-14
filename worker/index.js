// The site's static assets, plus comments under /api/ (wrangler.jsonc: run_worker_first).
//   POST /api/comments             a note from the viewer's Comment panel
//   GET  /api/comments?model=NAME  notes for one model, newest first, without their pictures
//   GET  /api/comments/ID.jpg      the picture sent with a note
// Notes are read and answered from the repo with tools/comments.py (make comments).
// Without a D1 binding (GitHub Pages, or wrangler.jsonc with no d1_databases) /api/ is a 404
// and the viewer hides its Comment button.

// Models this server takes notes for: the contract's `name` (model/options.yaml). check.py keeps them equal.
const MODELS = new Set(['example-house']);
const SHOWS = new Set(['proposed', 'existing']);
const MAX_BODY = 4000, MAX_IMAGE = 1_500_000, MAX_PINS = 40;

const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: {'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store'}});
const text = (s, n) => (typeof s === 'string' ? s.trim().slice(0, n) : '');
const num = v => (Number.isFinite(v) ? Math.round(v * 1000) / 1000 : null);

async function create(request, env) {
  if (Number(request.headers.get('content-length') || 0) > MAX_IMAGE + 200_000) return json({error: 'too big'}, 413);
  let c;
  try { c = await request.json(); } catch { return json({error: 'not JSON'}, 400); }
  if (c.website) return json({ok: true});   // honeypot: a field people never see, bots fill in
  if (!MODELS.has(c.model)) return json({error: 'unknown model'}, 400);
  const body = text(c.body, MAX_BODY);
  const pins = (Array.isArray(c.pins) ? c.pins : []).slice(0, MAX_PINS).map((p, i) => ({
    n: i + 1, x: num(p.x), y: num(p.y), z: num(p.z), id: text(p.id, 80) || null, label: text(p.label, 200) || null}));
  const strokes = Math.max(0, Math.min(500, Number(c.strokes) | 0));
  const image = typeof c.image === 'string' && c.image.startsWith('data:image/jpeg;base64,') && c.image.length <= MAX_IMAGE ? c.image : null;
  if (!body && !pins.length && !strokes) return json({error: 'write a note, tap something, or draw'}, 400);
  const cam = text(c.cam, 120);
  if (!/^-?[\d.]+(,-?[\d.]+){5}$/.test(cam)) return json({error: 'bad view'}, 400);
  // The deep link must point back at this site.
  const link = text(c.link, 1000);
  let same = false;
  try { same = new URL(link).origin === new URL(request.url).origin; } catch {}
  if (!same) return json({error: 'bad link'}, 400);
  const id = 'c_' + Date.now().toString(36) + crypto.getRandomValues(new Uint32Array(1))[0].toString(36).slice(0, 4);
  await env.DB.prepare(
    `INSERT INTO comments (id, created, model, author, body, link, show, cam, pins, strokes, image)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`)
    .bind(id, new Date().toISOString(), c.model, text(c.author, 60) || null, body, link,
      SHOWS.has(c.show) ? c.show : 'proposed', cam, JSON.stringify(pins), strokes, image)
    .run();
  return json({ok: true, id}, 201);
}

async function list(url, env) {
  const model = url.searchParams.get('model');
  if (!MODELS.has(model)) return json({error: 'unknown model'}, 400);
  const {results} = await env.DB.prepare(
    `SELECT id, created, author, body, link, show, cam, pins, strokes, image IS NOT NULL AS has_image,
            status, reply, replied
       FROM comments WHERE model = ? ORDER BY created DESC LIMIT 100`).bind(model).all();
  return json({comments: results.map(r => ({...r, pins: JSON.parse(r.pins), has_image: !!r.has_image}))});
}

async function picture(id, env) {
  const row = await env.DB.prepare('SELECT image FROM comments WHERE id = ?').bind(id).first();
  if (!row?.image) return new Response('not found', {status: 404});
  const bytes = Uint8Array.from(atob(row.image.split(',')[1]), ch => ch.charCodeAt(0));
  return new Response(bytes, {headers: {'content-type': 'image/jpeg', 'cache-control': 'public, max-age=86400'}});
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/') && !env.DB) return json({error: 'comments are off'}, 404);
    if (url.pathname === '/api/comments') {
      if (request.method === 'POST') return create(request, env);
      if (request.method === 'GET') return list(url, env);
      return json({error: 'method'}, 405);
    }
    const m = url.pathname.match(/^\/api\/comments\/(c_[a-z0-9]+)\.jpg$/);
    if (m && request.method === 'GET') return picture(m[1], env);
    if (url.pathname.startsWith('/api/')) return json({error: 'not found'}, 404);
    return env.ASSETS.fetch(request);
  },
};
