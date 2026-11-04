.PHONY: build drawings check check-drawings serve shots tours test-viewer demo-scan deploy-cloudflare

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

deploy-cloudflare: check
	npx wrangler@4 deploy
