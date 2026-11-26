# User guide

This guide describes the intended local demo flow. It assumes the model endpoint in `.env` is reachable.

## Start

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env   # then fill MODEL_NAME / BASE_URL / API_KEY
python app.py
```

Open <http://127.0.0.1:7860> in a browser.

## Phase 1 — Build a database from spreadsheets

1. In **DB Construction**, upload one or more `.xlsx`, `.xls` or `.csv` files (for a first run, use [`examples/sales.xlsx`](../examples/sales.xlsx)).
2. Start the initial design. The UI shows the parsed file structure, extracted sheet schemas and a Mermaid ER diagram.
3. Review the merge recommendations. To accept the suggested table merge, say so in the conversation box and update the schema.
4. Optional: edit the Mermaid code in the left panel and click **Update Changes**. **Undo Last Change** restores the previous version.
5. Click **Create Database**. The generated SQLite file appears under `created_DBs/`.

## Phase 2 — Ask questions

1. Switch to **Analysis with QA** and refresh the database list.
2. Select a database from the dropdown.
3. Ask a question in natural language, for example: *“Which 5 regions have the highest total revenue?”*
4. The answer shows the agent's execution history, final answer and result table. The raw result is also written to `result.csv`.

See [`examples/example_queries.md`](../examples/example_queries.md) for prompts that match the synthetic workbook.

## Notes

- All generated files live in `uploads/`, `temp/`, `created_DBs/` and `result.csv` under the repository root. They are gitignored.
- If an API call fails, check that `.env` is present, `MODEL_NAME` matches the endpoint's expected model id, and `BASE_URL`/`API_KEY` are correct.
