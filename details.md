# details

Tooling for this exercise. `Taskfile.yaml` builds three things: the design document, the slide deck, and the container that reviews a Terraform module.

## Layout

- `part1/` is the design document. Markdown is the source. The Excalidraw scene, its PNG, and `cover.png` sit beside it.
- `part2/` is the review program: Python package, lockfile, Dockerfile, tests.
- `present/` is one HTML file plus the pictures and lockups the slides use.
- `scripts/` exports diagrams and the deck PDF.
- `deliverables/` holds the document PDF, the deck PDF, and the diagram PNGs.
- `plans/` holds notes, earlier diagram versions, and a VHS tape. Those pictures stay there.
- `.cursor/` is the cloud-agent image, separate from the review container.

## Taskfile

[Task](https://taskfile.dev/) schema 3. Run it from the repo root. `{{.ROOT_DIR}}` is that root.

Review:

- `agent:build` builds `part2/Dockerfile` and tags it `module-review`.
- `agent:run` is interactive. It runs that image with `--env-file .env`.
- `agent:run:object-storage`, `agent:run:variable`, and `agent:run:project-factory` are presets for two refs of `straubt1/terraform-aws-object-storage` and for `terraform-google-modules/terraform-google-project-factory`. Each one calls a task named `run` and sets `GITHUB_REPO` and `GITHUB_CANDIDATE_REF`. The Docker task is `agent:run`, and its command reads `.env` only, so those variables stay inside Task.
- `agent:test` runs `uv run pytest -q -k "not langsmith"` in `part2`.
- `agent:test:tools` runs `tests/test_checks.py` and `tests/test_reader.py`.
- `expirement:create` runs the evaluation entry point. The task is spelled that way in the file.

Assets:

- `present` builds the slide image, removes any container of the same name, and bind-mounts `present/` over `/site`.
- `present:pdf` runs `scripts/export-pdf.sh`. Extra arguments pass through `{{.CLI_ARGS}}`.
- `diagrams` runs `scripts/export-diagrams.sh`.
- `docx` converts the design document to Word. `OUTPUT` overrides the path. `OPEN` defaults to `true` and opens the file on macOS.
- `docx:pdf` runs `docx` with `OPEN=false`, then converts that file to PDF.

## Review container

Python 3.12 (`part2/.python-version`). [uv](https://docs.astral.sh/uv/) installs from `uv.lock`. The image runs `uv sync --frozen --no-dev`. Tests use the dev group, which includes pytest. setuptools builds the package from `part2/src`.

Libraries beside the agent framework: `python-dotenv` and [Rich](https://github.com/Textualize/rich). The terminal UI is a Rich theme, tables, and a yes/no prompt. Proposed edits are printed with `difflib.unified_diff`.

GitHub access is the standard library. `urllib` calls `https://api.github.com` with `Accept: application/vnd.github+json`. `GH_TOKEN` comes from the environment. A review downloads the ref as a tarball, unpacks it in memory, and writes a directory when a CLI needs the tree. `terraform-docs` and Trivy run there through `subprocess`, with a 120 second timeout.

`part2/Dockerfile` starts from `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`. It installs pinned binaries and picks the archive from `dpkg --print-architecture`:

- terraform-docs 0.24.0
- Trivy 0.76.1

The interface check runs `terraform-docs markdown table` for inputs and outputs, with `--output-file ""` so the module is left unchanged. The security check runs `trivy config --format json --quiet`. The uv image entrypoint is `uv`, so the Dockerfile clears it and sets `CMD ["python", "-m", "review"]`. `.dockerignore` keeps `.env`, `.venv`, `plans`, `.cursor`, and PNGs out of the build.

`.env.example` lists `MODEL`, provider keys, `GITHUB_REPO`, `GITHUB_CANDIDATE_REF`, `TRIVY_SEVERITY`, and `GH_TOKEN`. `.env` is gitignored.

## Cursor agent image

`.cursor/Dockerfile` is Ubuntu 24.04. It installs Terraform 1.16.6, MiniStack 1.5.29 (pip), and uv. The `ubuntu` user has passwordless sudo. `.cursor/environment.json` builds that Dockerfile with context `..`.

Install runs `.cursor/scripts/install-check.sh`. It checks Terraform, MiniStack, and uv, syncs `part2` with `uv sync --frozen`, and clones `straubt1/terraform-aws-object-storage` when that checkout is missing, then fetches the `latest` branch and tags. The clone is gitignored.

Start runs `.cursor/scripts/start-ministack.sh`. MiniStack listens on port 4566 (`GATEWAY_PORT`). The script waits on `http://127.0.0.1:4566/_ministack/health`.

This image has Terraform and MiniStack. The review image has terraform-docs and Trivy.

## Slides

`present/index.html` is the deck. [Reveal.js](https://revealjs.com/) 5.1.0 comes from jsDelivr: `reset.css`, `reveal.css`, `reveal.js`, and the notes plugin. Color, type, and layout are local CSS on top of those two stylesheets.

The deck is 1280×720, margin 0, controls off, progress bar on, slide numbers off, hash routing on. Speaker notes are `<aside class="notes">`. A vertical stack is a parent `<section>` whose children are the slides. Left and right move between stacks. Up and down move inside the current one.

The face is TWK Lausanne, loaded as woff2 from `docs.langchain.com`, with Tahoma as the fallback. Lockups are the SVG files in `present/assets/`.

`present/Dockerfile` is `node:22-alpine` with `live-server` 1.2.2. It serves `/site` on port 80 and watches `index.html` and `assets`. `CHOKIDAR_USEPOLLING` is on so edits on the laptop show up through the ArcBox bind mount. The `docker run` line publishes no host port. ArcBox serves the container at http://langchain-presentation.arcbox.local/.

`scripts/export-pdf.sh` serves `present/` with `python3 -m http.server` on a free localhost port, waits until `curl` succeeds, then runs `npx --yes decktape@3.17.0` in `reveal` mode at 1280×720 (`--pause 1000`, `--load-pause 1500`). It looks for Google Chrome or Chromium, including `CHROME_PATH`, and sets `PUPPETEER_SKIP_DOWNLOAD` when it finds one so DeckTape uses that binary. The default file is `deliverables/presentation.pdf`.

## Diagrams

The file to edit is `.excalidraw`. The markdown and the slides embed the PNG next to it.

The editor is `excalidraw/excalidraw:latest`, published as `8080:80`. A save writes the scene back over the same path.

`scripts/export-diagrams.sh` renders with `npx --yes @moona3k/excalidraw-export` at scale 2. With no arguments it exports both copies of `langsmith-deployment.excalidraw` and `present/assets/module-review-v4.excalidraw`. The two deployment scenes have to be identical (`cmp`). The script stops when they differ. A PNG under `part1/` or `present/` is copied into `deliverables/`. A PNG under `plans/` stays beside its scene.

Scenes request Helvetica (`fontFamily` 2). The exporter draws Excalidraw's hand-drawn font, so the PNG needs a look after each export.

## Design document

Source is `part1/[InnovateCorp] LangSmith Self-Hosted Design Document.md`.

`\pagebreak` starts a new page. The figure is a markdown image, `langsmith-deployment.png`, resolved next to the file.

Style is an HCL block at the end of that same file, between `+++config` and `+++`. It sets the palette, TWK Lausanne for headings and body, Menlo for code, page margins in twips (720 top and bottom, 1200 left and right), table padding, paragraph and character styles, and a cover page. The cover uses `cover.png` full bleed, with the title, subtitle InnovateCorp, author, and October 2026.

[markdown-to-docx](https://github.com/straubt1/markdown-to-docx) is a separate Go program and has to be on `PATH`. This repo calls `convert`. The tool parses markdown with goldmark, the config block with HashiCorp HCL, and code color with Chroma. `task docx` creates `deliverables/`, runs `markdown-to-docx convert --verbose`, and opens the docx with macOS `open` when `OPEN` is `true`.

`task docx:pdf` then runs LibreOffice:

`/Applications/LibreOffice.app/Contents/MacOS/soffice --headless --convert-to pdf`

The conversion lands in a temp directory. The script moves the PDF beside the docx and removes the temp dir. The default pair is `deliverables/[InnovateCorp] LangSmith Self-Hosted Design Document.docx` and the PDF of the same name.

## Demo tape

`plans/demo.tape` is a [VHS](https://github.com/charmbracelet/vhs) script. `Require uv` checks that uv is installed. It types `GITHUB_CANDIDATE_REF=latest-variable uv run --directory part2 python -m review`, waits for the pull-request question, and answers `no`. Output is `plans/demo.gif`: Catppuccin Mocha, Roboto Mono, 1200×800, playback 0.75. Run it with the `vhs` CLI.
