"""打包入口：界面与子任务共用内置 Python 运行时。"""
import ast
import os
from pathlib import Path
import runpy
import subprocess
import sys


def main():
    # Frozen Python ignores PYTHONIOENCODING; GUI reads worker pipes as UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
    frozen = getattr(sys, 'frozen', False)
    home = Path(sys.executable).parent if frozen else Path(__file__).parent
    os.chdir(home)
    sys.path.insert(0, str(home))
    if '--worker-smoke' in sys.argv:
        print('WORKER_OK', flush=True); return
    if '--self-test' in sys.argv:
        import json
        import tkinter as tk
        from tkinter import ttk
        import requests
        from Crypto.Cipher import AES
        import gui
        manifest = json.loads((home/'文件清单.json').read_text(encoding='utf-8'))
        import hashlib
        for rel, digest in manifest.items():
            path = home/rel
            assert path.is_file(), 'Missing: '+rel
            assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, 'Changed: '+rel
            if path.suffix == '.py': ast.parse(path.read_text(encoding='utf-8-sig'))
        root = tk.Tk(); root.withdraw()
        app = gui.DailyGUI(root)
        def notebooks(w):
            for c in w.winfo_children():
                if isinstance(c, ttk.Notebook): yield c
                yield from notebooks(c)
        notebook = next(notebooks(root))
        names = [notebook.tab(t, 'text') for t in notebook.tabs()]
        assert names[names.index('抓宠')+1] == '新手任务'
        assert set(app.single_task_choices) == {'日常任务','日常副本'}
        assert 'RUN_CELEBRATION' in gui.TASK_PAGES['活动副本']
        assert hasattr(app, 'btn_cookie_login') and hasattr(app, 'var_save_log')
        root.destroy()
        result = subprocess.run([sys.executable, '--worker-smoke'] if frozen else
            [sys.executable, str(Path(__file__)), '--worker-smoke'], capture_output=True,
            text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        assert result.returncode == 0 and 'WORKER_OK' in result.stdout, result.stderr
        print('SELF_TEST_OK files=%s gui=ok worker=ok deps=ok' % len(manifest), flush=True)
        return
    if len(sys.argv)>1 and sys.argv[1]=='--worker':
        if len(sys.argv)<3: raise SystemExit('Missing task')
        script = home/Path(sys.argv[2]).name
        if not script.is_file() or script.suffix != '.py': raise SystemExit('Unknown task')
        sys.argv = [str(script)] + sys.argv[3:]
        runpy.run_path(str(script), run_name='__main__')
        return
    if os.name=='nt' and frozen:
        import ctypes
        console=ctypes.windll.kernel32.GetConsoleWindow()
        if console: ctypes.windll.user32.ShowWindow(console, 0)
    runpy.run_path(str(home/'gui.py'), run_name='__main__')


if __name__=='__main__':
    main()
