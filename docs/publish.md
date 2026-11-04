# Publish: a static site, two ways

The viewer is plain files: `index.html`, `app.js`, `style.css`, three.js vendored in
`site/vendor/` (MIT, license included), and the GLBs and `controls.json` that
`make build` writes. No server, database or keys. Anything that serves a folder works.
Here are two good ones.

| | GitHub Pages | Cloudflare Workers |
| --- | --- | --- |
| Setup | One setting, then push | A Cloudflare account and `wrangler` |
| URL | `you.github.io/repo` | `name.you.workers.dev`, or your own domain |
| Builds | In GitHub Actions on every push | On your machine (or CI if you add it) |
| Good for | An open-source example, a demo | A real house you'll keep revising, behind your own domain |
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

`wrangler.jsonc` points Workers at the same folder:

```jsonc
{
  "name": "3d-model-skill",
  "compatibility_date": "2026-11-01",
  "assets": { "directory": "./site", "not_found_handling": "none" }
}
```

```
$ make check
$ npx wrangler@4 login          # once
$ npx wrangler@4 deploy         # -> https://3d-model-skill.<you>.workers.dev
```

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
- **Weight.** Keep the first load under ~6 MB (`check.py` enforces it). Big real models
  want [Draco](https://google.github.io/draco/) compression and small textures.
- **Look on a phone.** Every control should work with a thumb, and Walk should work
  with the joystick.
