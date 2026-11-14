.PHONY: build drawings check check-drawings serve shots tours test-viewer demo-scan deploy-cloudflare stats sheet tokens comments dev

build:            ## model/*.yaml -> site/model, site/options, site/controls.json
	uv run model/build.py

drawings: build   ## site/drawings: SVG sheets, cut list, buy list (same numbers as the model)
	uv run model/drawings.py

check: drawings   ## spec sanity, door fit, option files, size budget, drawn = cut = bought
	uv run model/check.py

check-drawings:   ## with `make serve` running: readable labels, then PDFs
	uv run tools/check_drawings.py http://localhost:8000/drawings/ --pdf

serve: drawings   ## http://localhost:8000
	python3 -m http.server 8000 --directory site

shots:            ## README images from a running `make serve`
	uv run tools/screenshots.py http://localhost:8000/ docs/img

test-viewer:      ## drive a running `make serve` on an emulated iPhone
	uv run tools/check_viewer.py http://localhost:8000/

tours:            ## with `make serve` running: record every tour to docs/img
	uv run tools/record_tour.py http://localhost:8000/ 0 docs/img/tour-front-to-back
	uv run tools/record_tour.py http://localhost:8000/ 1 docs/img/tour-porch-options

demo-scan:        ## register a fake scan to the model, no phone needed
	uv run tools/register_scan.py --demo --out out/demo

stats:            ## size (raw, gzip, brotli) and counts of every built GLB; the build writes site/stats.json too
	python3 tools/glb_stats.py site/model/*.glb site/options/*.glb site/scan/*.glb

sheet:            ## one contact sheet of stills: make sheet OUT=out/sheet.jpg STILLS="street-dusk inside"
	uv run tools/contact_sheet.py $(OUT) --dir $(or $(DIR),docs/img) $(STILLS)

tokens:           ## log a session in model/worklog.yml: make tokens SESSION=<id prefix> TITLE="what it did"
	uv run tools/session_tokens.py --session $(SESSION) --title "$(TITLE)"

deploy-cloudflare: check   ## migrations first, so the comments table exists before the code that writes it
	npx wrangler@4 d1 migrations apply 3d-model-comments --remote
	npx wrangler@4 deploy

dev: drawings     ## the site plus the comments API and a local D1 on http://localhost:8787 (PORT=… to move it; `make serve` has no /api)
	npx wrangler@4 d1 migrations apply 3d-model-comments --local
	npx wrangler@4 dev --port $(or $(PORT),8787)

comments:         ## open notes from the viewer's Comment button (ALL=1 for every note, LOCAL=1 for `make dev`'s)
	uv run tools/comments.py $(if $(ALL),--all) $(if $(LOCAL),--local)
