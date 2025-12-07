# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Memory Bank Integration

**IMPORTANT: Always read the memory bank first before starting any task.** The `memory-bank/` directory contains comprehensive project documentation that provides essential context for development work.

### Core Memory Bank Files (Read Before Starting Tasks)

1. **`memory-bank/projectbrief.md`** - Foundation document defining core requirements and goals
2. **`memory-bank/productContext.md`** - Why this project exists and how it should work
3. **`memory-bank/activeContext.md`** - Current work focus, recent changes, and next steps
4. **`memory-bank/systemPatterns.md`** - System architecture and key technical decisions
5. **`memory-bank/techContext.md`** - Technologies used and development setup
6. **`memory-bank/progress.md`** - Current status and what's left to build

### Memory Bank Workflow

**Before Any Task:**
- Read relevant memory bank files to understand current context
- Check `activeContext.md` for recent changes and current focus
- Review `progress.md` for status and known issues

**After Significant Changes:**
- Update `activeContext.md` with new patterns or decisions
- Update `progress.md` with completed work and status changes
- Document new technical insights in appropriate files

## Project Overview

Sphene is a mature Discord bot that uses OpenAI's GPT-4o-mini for conversations. It responds to mentions, name calls, and replies with sophisticated conversation management. The bot features modular architecture, flexible storage options (local/S3), comprehensive error handling, and Docker/Kubernetes deployment support.

## Commands for Development

### Running the Bot
```bash
python app.py
```

### Testing
```bash
# Run all tests with coverage
python -m pytest

# Run tests with custom log level
LOG_LEVEL=DEBUG python -m pytest

# Run specific test file
python -m pytest tests/test_ai/test_client.py

# Use the shell script (includes coverage report)
./run_tests.sh
```

### Type Checking
```bash
mypy .
```

### Package Installation
```bash
# Production dependencies
pip install -r requirements.txt

# Development dependencies (includes pytest, mypy, etc.)
pip install -r requirements-dev.txt
```

### Docker
```bash
# Build image
docker build -t sphene-discord-bot .

# Run container
docker run --env-file .env sphene-discord-bot
```

## Architecture

The codebase follows a modular structure with clear separation of concerns:

- **`app.py`**: Main entry point that initializes and runs the SpheneBot
- **`config.py`**: Centralized configuration using environment variables
- **`ai/`**: OpenAI integration and conversation management
  - `client.py`: OpenAI client initialization
  - `conversation.py`: Conversation state and prompt management
- **`bot/`**: Discord bot implementation
  - `discord_bot.py`: Main bot class with setup and initialization
  - `commands.py`: Slash command definitions
  - `events.py`: Event handlers for messages and reactions
- **`utils/`**: Shared utilities
  - `channel_config.py`: Channel permission management
  - `s3_utils.py`: S3 storage operations
  - `text_utils.py`: Text processing utilities
  - `aws_clients.py`: AWS service clients
- **`log_utils/`**: Centralized logging setup
- **`storage/`**: Local file storage for prompts and configurations

### Key Design Patterns

1. **Storage Abstraction**: Both system prompts and channel configurations support local/S3 storage via environment variables
2. **Event-Driven Architecture**: Bot functionality is organized around Discord events (messages, reactions, commands)
3. **Conversation State Management**: Each channel maintains its own conversation history with automatic timeout and limits
4. **Modular Command System**: Slash commands are grouped and can be easily extended

### Configuration System

The bot uses environment variables for all configuration:
- `PROMPT_STORAGE_TYPE`: "local" or "s3" for system prompt storage
- `CHANNEL_CONFIG_STORAGE_TYPE`: "local" or "s3" for channel settings
- `BOT_NAME`: Name the bot responds to (default: "アサヒ")
- `COMMAND_GROUP_NAME`: Slash command group prefix

## Development Guidelines

### Code Quality Standards (Updated 2025/12/7)

This project maintains high code quality standards established through comprehensive refactoring:

1. **Function Length**: Keep functions under 20-30 lines; split functions exceeding 60 lines
2. **Naming Conventions**: Use underscore prefix (`_`) for all private/internal functions
3. **Error Handling**:
   - Always include `exc_info=True` in error logs for stack traces
   - Never expose internal error details to users (security risk)
   - Provide generic, user-friendly error messages
4. **Code Duplication**: Extract common logic into shared functions (see `translate_text()` pattern)
5. **Documentation**: Use Google Style docstrings with parameter descriptions, return values, and examples
6. **Testing**: Maintain 86%+ test coverage; update tests when refactoring internal APIs

### Code Patterns and Decision Making

The project follows established patterns documented in the memory bank:

- **Storage Abstraction Pattern**: Both system prompts and channel configurations support local/S3 storage
- **Event-Driven Architecture**: Bot functionality organized around Discord events
- **Hierarchical Error Handling**: Different error types with specific recovery strategies
- **Conversation State Management**: Channel-specific context with automatic timeouts
- **Configuration Pattern**: Dictionary-based configuration (e.g., `translate_text()` language configs)

Before implementing new features, review `memory-bank/systemPatterns.md` and `memory-bank/activeContext.md` for established patterns and current technical decisions.

### Knowledge Management

- **Document Patterns**: Record new architectural patterns in `memory-bank/systemPatterns.md`
- **Track Decisions**: Log important technical decisions in `memory-bank/activeContext.md`
- **Update Progress**: Maintain current status in `memory-bank/progress.md`
- **Context Continuity**: Use memory bank to maintain development context across sessions

### Memory Bank Integration

The `memory-bank/` directory contains comprehensive project documentation used by development tools. These files provide critical context about project goals, architecture decisions, current status, and established practices. Always reference these files when making significant changes to understand the project's intent, constraints, and evolution.

## Recent Refactoring (2025/12/7)

A comprehensive code review identified and resolved 10 issues across 3 phases:

### Phase 1: Critical Bug Fixes
- **[ai/conversation.py](ai/conversation.py:3)**: Added missing `time` module import
- **[utils/text_utils.py](utils/text_utils.py)**: Consolidated duplicate translation functions (30% code reduction)

### Phase 2: Quality Improvements
- **[ai/conversation.py](ai/conversation.py)**: Removed unreachable code and simplified comments
- **[bot/events.py](bot/events.py:194)**: Fixed security vulnerability (removed error details from user messages)
- **[utils/channel_config.py](utils/channel_config.py)**: Added stack traces to 5 error logs
- **[bot/events.py](bot/events.py)**: Standardized function naming (`handle_*` → `_handle_*`)

### Phase 3: Maintainability Enhancements
- **[ai/conversation.py](ai/conversation.py:175-180)**: Removed redundant type checks
- **[ai/conversation.py](ai/conversation.py:125-184)**: Split 60-line function into 3 smaller functions
- **Multiple files**: Enhanced docstrings with Google Style format
- **[utils/s3_utils.py](utils/s3_utils.py:66-72)**: Removed meaningless TYPE_CHECKING block

### Test Updates
- **[tests/test_bot/test_events.py](tests/test_bot/test_events.py)**: Updated imports and security test expectations
- **[tests/test_bot/test_reactions.py](tests/test_bot/test_reactions.py)**: Updated function references
- **[tests/test_ai/test_conversation.py](tests/test_ai/test_conversation.py)**: Updated default prompt expectations

**Result**: All 103 tests passing, 86% coverage maintained, significant improvements in security, maintainability, and code quality.