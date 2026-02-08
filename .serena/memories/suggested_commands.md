# Suggested Commands for Sphene Development

## Running the Application
- **Start the bot**: `python app.py`
- **Run in Docker**: `docker build -t sphene-discord-bot . && docker run --env-file .env sphene-discord-bot`

## Testing
- **Run all tests**: `./run_tests.sh` or `uv run python -m pytest`
- **Run with DEBUG logs**: `LOG_LEVEL=DEBUG uv run python -m pytest`
- **Run specific test**: `uv run python -m pytest tests/test_ai/test_client.py`

## Linting and Type Checking
- **Run mypy**: `uv run mypy .`

## Dependency Management
- **Install all dependencies (including dev)**: `uv sync --group dev`
- **Install production dependencies only**: `uv sync`
- **Update lockfile**: `uv lock`

## Environment Setup
- **Initialize .env**: `cp .env.sample .env`
- **Initialize system prompt**: `cp system.txt.sample storage/system.txt`
