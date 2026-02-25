try:
    from app.rq2_aggregate_metrics import main
except ModuleNotFoundError:  # Supports `python app/rq2.py`
    from rq2_aggregate_metrics import main


if __name__ == "__main__":
    main()
