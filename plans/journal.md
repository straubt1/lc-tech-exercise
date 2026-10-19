# Journal


## Important points

- Updating and publishing modules, without proper documentation is a common slow down.

## Questions to be prepared to answer

- What model and why?
- Secret storage and access?

## Flow

Created the plan a few times
Stubbed out agents and tools in python
Implemented Diff agent
- tools -> coded in agent (MCP didnt feel like a good fit)
- prompt updated since the results were trying to assign a version bump but was out of scope

Created evals codified
- unsure how to verify that a test passes

### Retool

We are going to start over - i have deleted all the agent code and diagrams, feel free to look back at the last commit to see what has changed but i do NOT want to carry that flow over.

Be as SIMPLE as possible
Use Langchain OSS code and Langgraph python packages everywhere
do not use pydantic unless you have a strong justification

I wanted to reduce the number of agents and their purpose.

Three Agents:
- Review Agent (async)
  - This looks at a git repo + ref an analyzes it for completeness and best practice
  - Ensures README.md properly shows all the needed things (variables, outputs, etc...) and that they match how they are used
  - Ensure CHANGELOG.md is up to date
  - [Future] examples/ directory has proper examples to help end users
  - Returns:
    - Status: Pass/Fail
    - Findings: [] array of objects if there is any recommendations
      - filename
      - finding
- Version Agent (async)
  - This looks at the git repo + ref, as well as existing tags in the format "vx.x.x" that represent past published versions
  - Checks to see if there are changes between the given ref and the last version published -> describes changes if any
  - Finds current version in CHANGELOG.md
  - Assuming that there are changes in the repo + ref that were made after the last published version, determine what the recommended next version should bump (major.minor.patch)
  - Returns:
    - Suggest Next Version: vx.x.x
    - Findings: [] array of objects if there is any recommendations
      - filename
      - finding
- Recommend Agent (runs after Review and Version agents complete)
  - Takes the findings of previous agents
  - Prints suggestions to output
  - Prompts for Human in the Loop on if suggestions should be created in a PR?
    - yes -> create a structured PR
    - no -> exit



---
Craig
- in order to meet the criteria to release
- take it a step further, what are the things that are outside of you
  - what does this affect outside?
  - go out and consuming workspaces