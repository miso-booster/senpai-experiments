try:
    from .answer_clustering import main
except ImportError:  # Supports `python app/rq3_v2/__main__.py`
    from answer_clustering import main


if __name__ == "__main__":
    main()

