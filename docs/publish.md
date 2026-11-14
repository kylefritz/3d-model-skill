# Publish: a static site, two ways

The viewer is plain files: `index.html`, `app.js`, `style.css`, three.js vendored in
`site/vendor/` (MIT, license included), and the GLBs and `controls.json` that
`make build` writes. No server, database or keys. Anything that serves a folder works.
Here are two good ones. The viewer's comments are the one extra: on Cloudflare they add a
small Worker and a free D1 database ([comments.md](comments.md)).

| | GitHub Pages | Cloudflare Workers |
| --- | --- | --- |
| Setup | One setting, then push | A Cloudflare account and `wrangler` |
| URL | `you.github.io/repo` | `name.you.workers.dev`, or your own domain |
| Builds | In GitHub Actions on every push | On your machine (or CI if you add it) |
| Good for | An open-source example, a demo | A real house you'll keep revising, behind your own domain |
| Comments | No (static only; the button hides) | Yes: a Worker and a free D1 database |
| Cost | Free | Free (static assets don't count as requests) |

## GitHub Pages

This repo deploys itself with `.github/workflows/pages.yml`: on every push to `main` it
runs `make build` and `make check`, then publishes `site/`. Pull requests build and
check without deploying.

For your own copy:

1. Push the repo to GitHub.
2. **Settings → Pages → Build and deployment → Source: GitHub Actions.** Or from a terminal:
   ```
   $ gh api -X POST repos/OWNER/REPO/pages -f build_type=workflow
   ```
3. Push to `main`. The Actions tab shows the URL when the deploy step finishes.

The built GLBs are not committed. The YAML is the source and CI builds the site, so the
deployed model is always one the checks passed.

A private repo needs a paid GitHub plan for Pages. Everything else here works on free.

Docs: [custom workflows for Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Cloudflare Workers (static assets)

`wrangler.jsonc` points Workers at the same folder, with a small script in front of `/api/*`
for the viewer's comments ([comments.md](comments.md)):

```jsonc
{
  "name": "3d-model-skill",
  "compatibility_date": "2026-10-30",
  "main": "worker/index.js",
  "assets": { "directory": "./site", "binding": "ASSETS", "not_found_handling": "none",
              "run_worker_first": ["/api/*"] },
  "d1_databases": [{ "binding": "DB", "database_name": "3d-model-comments",
                     "database_id": "<your-database-id>", "migrations_dir": "worker/migrations" }]
}
```

```
$ make check
$ npx wrangler@4 login                          # once
$ npx wrangler@4 d1 create 3d-model-comments    # once; paste the database_id into wrangler.jsonc
$ make deploy-cloudflare                        # migrations, then deploy -> https://3d-model-skill.<you>.workers.dev
```

No comments wanted: delete the `d1_databases` block. Only `/api/*` runs the script, so the
static files are still served as assets (free, not counted as requests).

For your own domain, the domain's DNS has to be on Cloudflare. Add a route and deploy
again. Cloudflare creates the DNS record and the certificate:

```jsonc
"routes": [{ "pattern": "house.example.com", "custom_domain": true }]
```

The hostname can't already have a CNAME record. Delete it first.

Running from CI or an agent's shell: create an API token with the "Edit Cloudflare
Workers" template and set `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` in the
environment. Keep the token out of git (direnv and an ignored `.envrc` work well).

Docs: [static assets](https://developers.cloudflare.com/workers/static-assets/),
[custom domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/).

## Compression

A GLB is mostly vertex positions and normals, and flat faces repeat the same normal three
times, so it compresses very well. The demo's `model/house.glb`, measured 2026-11-04:

| | Bytes |
| --- | --- |
| As built | 512 KB |
| gzip | 57 KB |
| brotli | 28 KB |
| `gltf-transform meshopt` | 107 KB |
| meshopt, then brotli | 12 KB |

All 74 GLBs on the site are 13.2 MB as built and 2.5 MB gzipped.

Two layers, and they stack:

1. **Transfer compression** (gzip or brotli). The host does this, so you change nothing
   in the files, but you have to check that it happens:
   ```
   $ curl -sI -H 'Accept-Encoding: gzip, br' https://you.github.io/3d-model-skill/model/house.glb | grep -i content-encoding
   content-encoding: gzip
   ```
   - **GitHub Pages** gzips `model/gltf-binary`. Nothing to do.
   - **Cloudflare** compresses HTML, JS and CSS but not `model/gltf-binary`, which isn't on
     its [list of compressed types](https://developers.cloudflare.com/speed/optimization/content/compression/).
     A real house measured on Workers static assets went out raw. Add a
     [compression rule](https://developers.cloudflare.com/rules/compression-rules/) for
     that content type on your zone (custom domains only; `workers.dev` can't take rules).

2. **Geometry compression**, inside the file:
   ```
   $ bunx @gltf-transform/cli@4 meshopt in.glb out.glb
   ```
   This quantizes positions to 16 bits (under 1 mm across a 40 m site) and packs the
   buffers with [meshoptimizer](https://meshoptimizer.org/). It works on any host, and the
   output still gzips. three needs the decoder:
   ```js
   import { MeshoptDecoder } from './vendor/meshopt_decoder.module.js';
   loader.setMeshoptDecoder(MeshoptDecoder);
   ```
   [Draco](https://google.github.io/draco/) compresses a little harder, but its decoder
   is a ~300 KB WASM download. For a house made of boxes, meshopt wins.

   Use `meshopt`, not `optimize`. `optimize` also runs `dedup`, `join` and `flatten`,
   which merge same-colored materials and same-material meshes. The viewer recolors by
   material name and moves nodes by name, so those merges break the parameters without
   any error. Run the drawings-vs-GLB check on the compressed file, since quantizing
   moves vertices by up to a millimeter.

If the host won't compress `model/gltf-binary` and you can't add a rule, compress it yourself:
keep a `house.glb.br` made with `brotli -q 9` next to the GLB, and have whatever serves it
(a Worker, your app) send that copy with `Content-Encoding: br` and `Content-Type:
model/gltf-binary` to a browser whose `Accept-Encoding` has `br`, and the raw file otherwise.
Serve the `.br` only while it matches the GLB beside it (compare a hash), or a rebuild ships a
stale model.

The demo ships only layer 1. Its first load is 0.7 MB before gzip and under 100 KB after,
so layer 2 would save tens of KB at the cost of a build step and a vendored decoder. A
scanned or textured house, or a big Blender export, is where layer 2 pays off.

## Size, stats and the work log

A big model is fine. Don't decimate, simplify or split it to make it smaller: that throws away
detail someone measured. Send it compressed (above) and keep the size where people see it.
Uncompressed float geometry shrinks about 4x with brotli; one 23 MB model went out under 6 MB.

- **Stats.** `make build` ends by writing `site/stats.json`: for every GLB its bytes, gzip and
  brotli size (brotli only when the `brotli` CLI is installed), triangles, vertices, draw calls,
  materials, textures and scan points. `tools/glb_stats.py` reads only the GLB's header and JSON
  chunk, standard library only. `make stats` prints the same table.
- **The viewer shows it.** "Model details", folded at the bottom of the panel, sums the files the
  current choices load (shell, each slot, the scan layer when it's on), says what goes over the
  wire, and gives every option's total. Over 15 MB or 1,000 draw calls it adds a plain hint
  that a phone will take longer. A hint, never a cap.
- **The work log.** `model/worklog.yml` lists the Claude Code sessions that built the model and
  their tokens by model, lead and workers apart. After a session:
  ```
  $ make tokens SESSION=<id prefix> TITLE="rear door options, round 2"
  $ uv run tools/session_tokens.py --show
  ```
  It finds `~/.claude/projects/*/<session>.jsonl` (the lead) and the subagent transcripts under
  `<session>/` (the workers), counts each message once, and appends an entry (re-running replaces
  it). `--from`/`--to` keep a window of a session that also did other work. The build prices it
  into `stats.json`, and the viewer shows a table with an **API list-price equivalent**: work on
  a subscription isn't billed that way, so it's labelled an equivalent, not a cost. The prices
  are one dated dict at the top of `tools/session_tokens.py`. They go stale, so check them. A
  model it doesn't know shows its tokens and a `+` on the cost.

The worklog is published with the site when it exists. Leave it out of a public repo if the
session titles say more than you want to share.

## Is the live site what you built?

Two checks close the loop after a deploy:

- **Fingerprint.** `controls.json` carries `source_sha256`: a hash of `model/*.yaml`,
  `build.py` and `drawings.py`. `make check` fails if it doesn't match today's sources, so
  you can't publish a stale export by accident.
- **Byte for byte.** `tools/verify_live.py` fetches every file of the deployed tree from
  the live URL (cache-busted, retrying while the CDN catches up) and compares hashes.
  The workflow's `verify` job runs it against the exact artifact it deployed.

```
$ uv run tools/verify_live.py https://you.github.io/3d-model-skill/
ok   121 files live and identical; sources de7963a80377
```

## Before you publish a real house

- **Strip private notes.** Correspondence, addresses, lock models, alarm panels: none of
  it belongs in a GLB anyone can download. Export only geometry and a contract.
- **Weight.** The demo's `check.py` keeps its first load under 6 MB, because a made-up house
  of boxes has no reason to be bigger. A real one may be: raise the budget rather than cut
  detail, serve it compressed, and let "Model details" say how big it is.
- **Look on a phone.** Every control should work with a thumb, and Walk should work
  with the joystick.
