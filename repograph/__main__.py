"""Allow ``python -m repograph`` → entrypoint (same as console script)."""
from repograph.entry import main

if __name__ == "__main__":
    main()
