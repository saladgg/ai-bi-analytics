import pandas as pd
import plotly.express as px
from plotly.graph_objects import Figure


def _is_measure(series: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(
        series
    )


def _is_identifier(column: object) -> bool:
    name = str(column).lower()
    return name == "id" or name.endswith("_id")


def pick_chart_columns(df: pd.DataFrame) -> tuple[str, str] | None:
    """
    The (x, y) columns to chart: the first non-numeric column against the
    first numeric one. A result with only numeric columns charts the first
    against the second. Id columns (``id``, ``*_id``) are neither. None
    when nothing sensible can be drawn.
    """
    columns = [c for c in df.columns if not _is_identifier(c)]
    measures = [c for c in columns if _is_measure(df[c])]
    labels = [c for c in columns if c not in measures]
    if not measures:
        return None
    if labels:
        return labels[0], measures[0]
    if len(measures) >= 2:
        return measures[0], measures[1]
    return None


def auto_chart(df: pd.DataFrame) -> Figure | None:
    if df.empty:
        return None
    columns = pick_chart_columns(df)
    if columns is None:
        return None
    x_col, y_col = columns
    return px.bar(df, x=x_col, y=y_col, title=f"{y_col} by {x_col}")
