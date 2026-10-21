"""Repository entrypoint for the shared portable skill installer."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      'skills/literature-review/scripts/runtime'))
from litreview_core.skill_installation import install, main


if __name__ == '__main__':
    raise SystemExit(main())
