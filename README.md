# lc-tech-exercise

Take-home exercise for the Deployed Architect, Professional Services role.

The scenario is a Professional Services engagement with InnovateCorp. It has two parts: a design for a self-hosted LangSmith deployment, and a multi-agent system that reviews a Terraform module before it is published. A person approves the suggested changes before a pull request is opened.

## deliverables

The completed submission assets.

- `[InnovateCorp] LangSmith Self-Hosted Design Document.pdf` is the design document.
- `presentation.pdf` is the Presentation deck.
- `langsmith-deployment.png` is the deployment diagram used in the design document and the deck.
- `module-review-v4.png` is the agent diagram used in the deck.

## part1

Source for the design document.

`[InnovateCorp] LangSmith Self-Hosted Design Document.md` is the markdown. `langsmith-deployment.excalidraw` is the diagram that markdown embeds, and the PNG beside it is the picture. Building the document writes the PDF into `deliverables/`.

## part2

The agent, the evaluations, and a few utilities used during development.

The review system is in `src/review/`.

- `prompts/` holds the instructions for each specialist: interface (variables and outputs match the readme), security (Trivy findings), release (whether the module is ready, and the next version), and recommend (file edits and pull request text). `groundedness.md` is the check used when scoring recommendations.
- `agents/` builds those specialists. Each agent loads its prompt and returns a structured result.
- `graph.py` defines `build_graph`. That function assembles the LangGraph: confirm the repository, run interface, security, and release together, then recommend, then stop for a person to approve or decline the pull request.
- `evals.py`, with the dataset in `evals/tf-module-review.json`, runs the LangSmith evaluation.
- `util/` has scripts for deleting LangSmith projects and datasets while developing.
- `tests/` covers the graph, agents, tools, and evaluators.

`Taskfile.yaml` at the repository root runs the agent, the unit tests, and a LangSmith experiment.

## present

The stakeholder presentation, built with [Reveal.js](https://revealjs.com/).

`index.html` is the deck. Diagram scenes live in `assets/` next to the pictures the slides use: `langsmith-deployment.excalidraw` and `module-review-v4.excalidraw`. Lockups are the SVG files in that same folder. Exporting the deck writes `deliverables/presentation.pdf`.


## Demo


![Demo](deliverables/demo.mp4)