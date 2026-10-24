# Prompt template

This file is an example for writing specialist prompts. Nothing loads it. Do not pass `template.md` to `read_prompt` or `make`.

`release.md` is this template filled in. Copy that shape. `recommend.md` and `groundedness.md` are different jobs and do not follow it.

The prompt file is the system prompt the model reads. Keep author notes here. A specialist file states only that specialist's job.

## How a prompt is wired

- The file is `part2/src/review/prompts/<specialty>.md`.
- `part2/src/review/agents/<specialty>.py` holds the JSON schema and calls `make(model, tools, "<specialty>.md", SCHEMA, "<specialty>")`.
- `## Returns` must match that schema. Same field names, same enums, same required fields. A value the checks use but the schema does not list is a working value. Say that it is not returned. `unreleased_version` in `release.md` is a working value. `suggested_version` and `bump` are returned.
- The graph passes the tools. Name only those tools. The model cannot call a tool this agent was not given.
- `graph.py` sends a short user message and stores the structured response. The user message repeats the return fields. It must not contradict a check. A line such as "findings is empty" will drop a check that is supposed to report.
- `normalize.status` forces the bad status when any finding remains. `normalize.findings` drops an item with an empty `finding`. A blank filename becomes `module`.
- Recommend lists every finding and edits the named file. A finding whose text contains `nothing new to release` does not add its file. Write the concrete change the file should get.

Interface and security use `pass` and `fail`. Release uses `ready` and `not ready`. Use the enum on that schema.

## File shape

```markdown
# <Specialty>

You are the <specialty> specialist. <One sentence: the only job this agent owns.>

## Returns

Return `<field>`, `<field>`, and `findings`.

- `<field>` is `<allowed values>`.
- `findings` is a list. Each item has `filename` and `finding`. Use filename `<file this specialty reports on>`.

Any finding means `status` is `<bad>`. When every check reports nothing, `status` is `<good>` and `findings` is `[]`.

## Tools

Call these tools, in this order, then answer from their results. Do not fetch git yourself. Do not call any other tool.

### <tool_name>

- What: <what the tool returns, in the words of its implementation>.
- When: <once, and where in the order>.
- How: <arguments, or no arguments>. <What to read from the result.>

## <Working value or returned decision>

Set `<name>` before the checks. Say whether it is returned.

<The rules that set it. Concrete examples. The order to test cases, so an earlier case wins.>

## Checks

Run every check that applies. Each check adds zero or many findings. These are the only checks. <Name the neighboring specialty whose problems this agent must leave alone.>

### <Check name>

<What to read, and what to ignore.>

Report nothing when <the pass case>.

Report <one finding, or one finding per mismatch> when <the fail case>. <What the finding text must name. Which filename. An example of the sentence.>

<If this check can stop the rest: say to skip the later checks. A check does not clear findings from the other checks.>
```

## Add a check

Add a `###` section under `## Checks` in the specialist file. Do not add a return field for it.

State four things:

- When the check applies, and when it reports nothing.
- Whether it reports one finding or one finding per mismatch.
- The filename, and the words the finding must include.
- Any working value it uses. If that value does not exist yet, add a `##` section above `## Checks` that sets it before the checks, and name it in the finding text.

Leave the other checks as they are. Do not let an earlier check empty `findings`.

Then read the user message in `graph.py` for that agent. If it forces a status or an empty findings list, change that sentence so this check can still report. If the node overwrites the findings after the model returns, the check never reaches the review.

## Add a specialist

1. Copy the file shape into `prompts/<specialty>.md`. The first sentence is `You are the <specialty> specialist.`
2. Add `agents/<specialty>.py`. The schema `required` list is the `## Returns` list. A finding specialist uses `findings_schema()`.
3. Add a tool builder that returns only this specialist's tools. Describe each tool in the prompt from what the function actually returns.
4. Add a graph node. The user message names the repo, the ref, the tool calls, and the return fields. Store `status` and `findings` with `normalize.status`. Pass that specialist's good and bad status words.
5. A test that looks for a phrase in the system prompt must use the first sentence of the new file.

## Voice

Short sentences. One concrete example where a rule is easy to miss. Say what to report, then the few limits that stop a known mistake: do not fetch git, do not call another tool, do not report another specialty's problem, do not name a fix without the value that belongs in it.
