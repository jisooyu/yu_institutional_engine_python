"""Minimal validation for the Dash application."""

from app import AI_CHAIN, ETF_ROWS, SECTORS, app


def main() -> None:
    assert app.title == "Institutional Flow — Rotation Intelligence"
    assert len(SECTORS) == 6
    assert len(ETF_ROWS) == 8
    assert len(AI_CHAIN) == 8
    layout = app.layout()
    assert layout is not None
    print("Smoke test passed: dashboard layout and datasets are available.")


if __name__ == "__main__":
    main()
