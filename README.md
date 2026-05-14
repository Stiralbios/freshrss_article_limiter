# FreshRSS Articles Limiter

Limit the number of unread articles in FreshRSS by having an LLM rate them and marking the lower-rated ones as read.

## How it works

The script:
1. Calls the FreshRSS API to get all unread articles
2. Organizes them into structured objects (id, title, author, content, URL, feed_id)
3. Rates each article 0–100 via LLM based on your personalized prompt
4. Caches ratings to a JSON file to avoid redundant LLM calls on future runs
5. Sorts articles by rating (descending)
6. Keeps the top N articles unread, marks the rest as read via FreshRSS API

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `FRESHRSS_PYTHON_API_HOST` | Yes | FreshRSS instance URL |
| `FRESHRSS_PYTHON_API_USERNAME` | Yes | API username |
| `FRESHRSS_PYTHON_API_PASSWORD` | Yes | API password |
| `OPENAI_BASE_URL` | Yes | LLM API base URL (e.g., Ollama, OpenRouter, OpenAI) |
| `OPENAI_API_KEY` | Yes | LLM API key |
| `INFERENCE_MODEL` | Yes | Model name (e.g., `deepseek-v4-flash:cloud`) |
| `USER_PROMPT_FILENAME` | Yes | Path to prompt file (e.g., `user_prompt.txt`) |
| `NB_ARTICLES_KEEPT` | Yes | Number of top-rated articles to keep unread |
| `ENABLE_THINKING` | No | Set to `true` to enable model reasoning (default: false) |
| `REASONING_EFFORT` | No | Reasoning effort: `low`, `medium`, `high` (default: medium) |
| `CACHE_FILENAME` | No | JSON cache file path (default: `scores_cache.json`) |

## CLI Arguments

- `--dry-run`: Do not mark articles as read (limits to 5 articles by default)
- `--nb-evaluated`: Override dry-run limit (default: 5)
- `--verbose`: Show LLM prompts, responses, and JSON dumps
- `--rate-limiter`: Seconds between LLM calls

## Running with Docker

```bash
# Dry-run (test without marking articles as read)
make dry-run

# Live run (actually marks lower-rated articles as read)
make run
```

The cache file is automatically persisted between Docker runs via a volume mount.

## Setup

Python 3.13
Use a venv
Install deps: `pip install -r requirements.txt`

Key libs: `freshrss-api`, `langchain-openai`, `python-dotenv`

## Coding standard

- Use `requirements.txt`
- Use TDD, mock external calls (FreshRSS, LLM)
- Add logs
- Use `--dry-run` to test real API calls
- YAGNI, DRY
- Stateless app (state is externalized to FreshRSS + cache file)

## Note

Vibecodded for personal use, don't expect quality.
