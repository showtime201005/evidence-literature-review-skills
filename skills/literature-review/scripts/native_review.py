"""Entry for the native cold review workflow (requires native dependencies)."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'runtime'))
from litreview_core.native_review import main

if __name__=='__main__':
    main()
