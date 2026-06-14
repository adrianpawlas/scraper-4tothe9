"""Entry point: python -m scraper"""
import sys
from scraper.run import main

if __name__ == "__main__":
    main(argv=sys.argv[1:])
