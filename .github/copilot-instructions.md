# Project Context: Memory Bank Summary (from Cline)

Please assume the following documentation structure has been created as a shared source of truth. It defines the complete project context and should inform all your responses.

## Memory Bank Structure

All files are Markdown format, located under the `memory-bank/` directory. Each file provides specific context:

- `projectbrief.md`: Core goals, scope, and motivation of the project
- `productContext.md`: Target users, UX goals, problems to solve
- `systemPatterns.md`: Architecture, design patterns, and system decisions
- `techContext.md`: Technologies used, toolchains, setup notes
- `activeContext.md`: Current status, key learnings, implementation details
- `progress.md`: What’s done, what’s pending, open issues

There may also be additional context files for:
- Complex features
- API integration
- Deployment, testing, and operations

## Copilot Agent Instructions

When reviewing or generating code, **always reflect the context above**. Especially prioritize alignment with:
- Patterns and system design (`systemPatterns.md`)
- Technologies and constraints (`techContext.md`)
- Current task focus and recent changes (`activeContext.md`)

If a file update or code change is ambiguous, consider asking:
> “Does this align with the systemPatterns or activeContext?”

## Final Notes

This memory bank is maintained externally using Cline. You are not expected to edit it directly, but all your work should remain consistent with its contents.

