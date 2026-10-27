# Contributing

Thank you for helping. Issues and pull requests are welcome.

## Set up

```bash
git clone https://github.com/actogram/scholar-mcp
cd scholar-mcp
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Before you open a pull request

- `ruff check src tests` and `ruff format --check src tests` pass.
- `pytest` passes. Tests run offline on recorded answers in `tests/fixtures`; add a fixture when you add a source or
  change a parser, and replace any e-mail address in it with `author@example.org`.
- `pytest -m network` passes when you touch a source (it makes a few real requests).
- New behaviour has a test, and the README says how to use it.
- Keep each change to one topic, and describe why in the pull request.

## Adding a source

A source lives in `src/labscout/sources/`, uses the shared client in `http.py` (pacing, retries, cache), and
returns the records in `models.py`. Use only official APIs, respect their rate limits and terms, and list the source in
the README table with its terms.

## Personal data

Do not add e-mail addresses, contact details or anything that is not already public in a publication, grant or trial
record. Do not commit API keys or `.env` files.
