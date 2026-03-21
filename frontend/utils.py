import pandas as pd
import plotly.express as px


def auto_chart(df: pd.DataFrame):
    if df.shape[1] < 2:
        return None

    x_col = df.columns[2]
    y_col = df.columns[3]

    if pd.api.types.is_numeric_dtype(df[y_col]):
        return px.bar(df, x=x_col, y=y_col, title="Visualization")

    return None