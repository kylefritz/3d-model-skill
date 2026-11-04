.PHONY: build check serve shots test-viewer demo-scan deploy-cloudflare

build:            ## model/*.yaml -> site/model, site/options, site/controls.json
	uv run model/build.py

check: build      ## spec sanity, door fit, every option file present, size budget
	uv run model/check.py

serve: build      ## http://localhost:8000
	python3 -m http.server 8000 --directory site

shots:            ## README images from a running `make serve`
	uv run tools/screenshots.py http://localhost:8000/ docs/img

test-viewer:      ## drive a running `make serve` on an emulated iPhone
	uv run tools/check_viewer.py http://localhost:8000/

demo-scan:        ## register a fake scan to the model, no phone needed
	uv run tools/register_scan.py --demo --out out/demo

deploy-cloudflare: check
	npx wrangler@4 deploy
