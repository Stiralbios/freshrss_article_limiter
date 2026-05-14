# FreshRSS Articles Limiter

Limit the number of article left unread in freshrss

## How does it work

The script:
- Call the freshrss api to get all the unread items
- Organize them in a json, with id, title, category, description, content
- Send the item one by one to a llm to rate them (0 to 100) with the configured prompt. The llm should only send back a floating number between 0 to 100 (if possible as structured json)
- Add the rate back to the json
- Order the items by the ranking
- Filter the order to separated the X best items from the rest
- Call the freshrss API to mark the worst filtered item as read


## Environment variables

FRESHRSS_PYTHON_API_HOST
FRESHRSS_PYTHON_API_USERNAME
FRESHRSS_PYTHON_API_PASSWORD
OPENAI_BASE_URL
OPENAI_API_KEY
INFERENCE_MODEL
USER_PROMPT_FILENAME
NB_ARTICLES_KEEPT
RATE_LIMITER_DELAY  # Delay in seconds between LLM calls (default: 0)

## CLI Arguments

- `--dry-run`: do not mark the freshrss feeds are read (limits to 5 articles)
- `--verbose`: show LLM prompts, responses, and JSON dumps
- `--rate-limiter`: override RATE_LIMITER_DELAY (seconds between LLM calls)

## Loaded file

Python 3.13
Use a venv
libs: freshrss-api, langchain

## Coding standard

- Use requirement.txt
- Use TDD, mock the calls to external tools (freshrss, llm)
- Add logs
- Use the dry-run if you need to test real api call
- YAGNI, DRY
- The app is stateless

## Note

Vibecodded for personal use, don't expect quality