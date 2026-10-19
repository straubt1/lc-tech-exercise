---
name: excalidraw-diagrams
description: >-
  Authors and revises Excalidraw scenes in plans/diagrams, exports a PNG, and
  inspects that image before finishing. Use when creating, versioning, or
  editing an .excalidraw diagram, or when the user asks for an architecture
  diagram.
---

# Excalidraw diagrams

The `.excalidraw` file in `plans/diagrams/` is the source. A PNG next to it is the preview.

The user can also open the JSON at http://localhost:8080 and export it back over the same path.

```bash
docker run -d -p 8080:80 --name my-excalidraw-instance excalidraw/excalidraw:latest
```

The image listens on container port 80.

## Edit, then look

After creating or changing a scene:

1. Patch the JSON. Keep element `id`s. Do not regenerate a scene the user has saved. A new version is a new file (`name-v2.excalidraw`). Leave the previous file untouched. Do not write the version on the canvas.
2. Export a PNG beside the scene:

```bash
npx @moona3k/excalidraw-export plans/diagrams/<name>.excalidraw -o plans/diagrams/<name>.png --scale 2
```

3. Read the PNG and check the picture: clipped or overlapping text, missing arrows, a diamond branch that does not land on its box, a legend that covers a card, and uneven gaps.
4. Adjust the JSON and export again until the picture is clean.
5. Leave both files. The JSON stays the file to edit. The PNG is the view of it.

The exporter draws text in Excalidraw's hand-drawn font, not Helvetica. Expect the picture to differ slightly from the editor. Fix overlap and clipping. Do not restyle the scene to match that font.

## Layout

Use Helvetica (`fontFamily` 2). Keep each column only as wide as its longest line. Stack lists one item per line.

- Purpose note above each agent: fill `#e7f5ff`, `strokeWidth` 0, no arrow.
- Card under the step: `prompt` and the filename on one line, then `tools`, then `output`. One tool or state field per line. `none` is `#868e96`.
- Output rows sit on `#b2f2bb`.
- Excalidraw has no bold. Draw a label twice, 0.7px apart.
- A branch is a `diamond` with yes and no arrows, not a flat list.
- Something that is not a step has `frameId` null and no arrows.
- Mission text is a top callout: fill `#fff4e6`, roughness 0, left bar `#e8590c`.

Legend swatches: `#a5d8ff` agent, `#ffec99` placeholder, `#ffd8a8` human gate, `#e9ecef` start and end, `#b2f2bb` output.

Use readable ids (`node-diff`, `card-diff`, `text-card-diff-tool-1`, `diamond-ready`). Keep arrow bindings and `boundElements` in sync. Give new elements the next fractional `index` (`a0`…`az`, then `b00`).
