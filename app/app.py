import dash
import dash_bootstrap_components as dbc
from app.components.navbar import navbar

app = dash.Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.DARKLY],
    suppress_callback_exceptions=True,
)

server = app.server  # expose Flask server for Gunicorn

app.layout = dbc.Container(
    [
        navbar,
        dash.page_container,
    ],
    fluid=True,
    className="px-0",
)

if __name__ == "__main__":
    app.run(debug=True)
