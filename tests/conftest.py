import os
import sys

# Put the repo root on sys.path so `import browser_search` (a top-level module,
# matching opsdisk's flat layout) resolves when pytest is run from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
