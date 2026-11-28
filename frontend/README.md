# Frontend (Streamlit UI)

This is a minimal Streamlit-based UI for interacting with the AI BI backend.

## ⚠️ Purpose

This frontend is **intended for testing and demonstration purposes only**.

It provides a simple interface to:
- Submit natural language queries
- View generated SQL
- Display query results
- Render basic visualizations
- Read explanations from the backend

## 🚫 Why This Is Not Production-Ready

This UI is deliberately lightweight and has several limitations:

- No authentication or user management
- API key is handled client-side (not secure for public use)
- No input validation or rate limiting
- No persistent state (no saved queries/dashboards)
- Limited visualization logic: one bar chart, the first label column
  against the first numeric column (id columns skipped)

API errors are shown with their message, error code and request id (to
match the server log), and truncated results and the model's assumptions
are flagged above the table.

## Set environment variables:

```bash
export API_KEY=your-api-key
export API_BASE_URL=http://localhost:8000   # the default
```

## ▶️ Run the app

The demo's dependencies (Streamlit, pandas, Plotly, requests) live in the
`frontend` dependency group, so the API image doesn't carry them.
`make install-dev` installs them; `make run_frontend` runs the app with them:

```bash
make run_frontend   # = uv run --group frontend streamlit run frontend/streamlit_app.py
```
