# Contributing

1. `pip install -r requirements-dev.txt`
2. New data or document styles: extend `sckg/data/generator.py` (with gold annotations) and run `make data`.
3. `make lint test eval`. Any false merge in entity resolution blocks a merge.
