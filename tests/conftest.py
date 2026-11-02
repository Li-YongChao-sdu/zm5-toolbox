import os
import sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app')
if APP not in sys.path:
    sys.path.insert(0, APP)
