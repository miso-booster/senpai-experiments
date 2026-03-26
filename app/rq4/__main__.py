try:
    from .aggregate_metrics import main
except ImportError:  # Supports `python app/rq4/__main__.py`
    from aggregate_metrics import main


if __name__ == "__main__":
    main()
