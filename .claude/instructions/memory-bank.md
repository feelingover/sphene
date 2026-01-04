# Claude Code's Memory Bank

I am Claude Code, an AI assistant with conversation context continuity. Unlike tools that reset between sessions, I maintain context across our conversation, but I rely on the Memory Bank for long-term project knowledge, architectural decisions, and established patterns.

## Memory Bank Structure

The Memory Bank consists of core files in Markdown format. Files build upon each other in a clear hierarchy:

**Reading Order:**
1. `projectbrief.md` → Foundation document (core requirements and goals)
2. `productContext.md` → Why this exists and how it works
3. `systemPatterns.md` → Architecture and key technical decisions
4. `techContext.md` → Technologies and development setup
5. `activeContext.md` → Current focus, recent changes, next steps
6. `progress.md` → Current status and remaining work

### Core Files (Required)

These files are essential for understanding the project and its current state.

1. **`projectbrief.md`**
   - Foundation document that shapes all other files
   - Defines core requirements and goals
   - Source of truth for project scope

2. **`productContext.md`**
   - Why this project exists
   - Problems it solves
   - How it should work
   - User experience goals

3. **`activeContext.md`**
   - Current work focus
   - Recent changes
   - Next steps
   - Active decisions and considerations

4. **`systemPatterns.md`**
   - System architecture
   - Key technical decisions
   - Design patterns in use
   - Component relationships

5. **`techContext.md`**
   - Technologies used
   - Development setup
   - Technical constraints
   - Dependencies

6. **`progress.md`**
   - What works
   - What's left to build
   - Current status
   - Known issues

### Directory Structure

```
.claude/instructions/memory-bank/
├── projectbrief.md
├── productContext.md
├── activeContext.md
├── systemPatterns.md
├── techContext.md
└── progress.md
```

### Additional Context

Create additional files/folders within memory-bank/ when they help organize:
- Complex feature documentation
- Integration specifications
- API documentation
- Testing strategies
- Deployment procedures

## Core Workflows

### Starting a New Task

When I start a new task, I follow this process:

**1. Check Memory Bank**
   - Read relevant memory bank files based on task scope
   - I don't need to read all files every time due to conversation context continuity
   - Focus on files directly related to the current task

**2. Verify Context**
   - Confirm understanding with user if needed
   - Check for recent changes in `activeContext.md`
   - Review known issues in `progress.md`

**3. Develop Strategy**
   - For complex tasks, use **Plan Mode** to design approach
   - For multi-step tasks, use **TodoWrite** to track progress
   - Leverage specialized **Agents** (Explore, Plan) when needed

**4. Present Approach**
   - Share implementation plan with user
   - Get approval for significant changes
   - Begin execution

### Executing Tasks

When executing tasks, I follow this process:

**1. Check Memory Bank**
   - Reference relevant files based on task type
   - `systemPatterns.md` for architectural decisions
   - `techContext.md` for technology-specific constraints
   - `activeContext.md` for current project focus

**2. Use Claude Code Tools**
   - **TodoWrite**: Track progress on complex tasks
   - **Plan Mode**: Design approach for significant changes
   - **WebSearch**: Get latest documentation when needed
   - **Agents**: Delegate exploration or planning tasks

**3. Execute Task**
   - Follow established patterns from Memory Bank
   - Use appropriate tools for the task
   - Maintain code quality standards

**4. Document Changes**
   - Update `activeContext.md` with new patterns or decisions
   - Update `progress.md` with completed work
   - Document architectural insights in `systemPatterns.md`

## Documentation Updates

Memory Bank updates occur when:
1. Discovering new project patterns
2. After implementing significant changes
3. When architectural decisions are made
4. When user requests **update memory bank**

### Update Process

**When to Update Each File:**

- **`activeContext.md`**: Most frequent updates
  - After significant feature implementations
  - When making important technical decisions
  - When changing current project focus

- **`progress.md`**: Regular updates
  - After completing major tasks
  - When discovering new issues
  - When project status changes

- **`systemPatterns.md`**: Occasional updates
  - When introducing new architectural patterns
  - When making significant refactoring decisions

- **`techContext.md`**: Infrequent updates
  - When adding new technologies or dependencies
  - When development setup changes

- **`projectbrief.md`** and **`productContext.md`**: Rare updates
  - When project scope or goals change
  - When core requirements evolve

### Update Best Practices

- Use specific, dated entries when adding to history sections
- Keep information concise and relevant
- Remove outdated information to maintain clarity
- Cross-reference related files when appropriate

## Claude Code Tools Integration

### TodoWrite
Use for complex multi-step tasks:
- Break down large features into manageable steps
- Track progress visibly for the user
- Ensure no steps are forgotten

### Plan Mode
Use for significant changes:
- Launches Explore agents to understand codebase
- Creates detailed implementation plans
- Gets user approval before execution

### Agents
Use for specialized tasks:
- **Explore**: Find files, understand architecture, discover patterns
- **Plan**: Design implementation approaches
- **Bug Hunter**: Create comprehensive test cases
- **Code Security Reviewer**: Security and performance review

### WebSearch
Use when you need current information:
- Latest documentation for libraries
- Recent API changes
- Best practices updates

## Best Practices

- **Reference selectively**: Read only the Memory Bank files relevant to your current task
- **Update actively**: Keep `activeContext.md` and `progress.md` current
- **Document decisions**: Record architectural choices in `systemPatterns.md`
- **Maintain continuity**: Use Memory Bank to ensure consistency across sessions
- **Leverage tools**: Use TodoWrite, Plan Mode, and Agents proactively for complex work

REMEMBER: Claude Code maintains conversation context, so the Memory Bank complements this by providing long-term project knowledge, established patterns, and architectural decisions. It's a reference guide for consistency, not a requirement to read every time.
