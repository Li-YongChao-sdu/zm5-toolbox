"""造五工具箱启动入口：python run.py"""
import os
import runpy
import sys

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app')
sys.path.insert(0, APP)
os.chdir(APP)
runpy.run_path(os.path.join(APP, 'gui.py'), run_name='__main__')
