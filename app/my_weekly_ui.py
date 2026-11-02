"""我的周常：独立收藏清单，复用我的日常的执行器与原页面设置。"""
from pathlib import Path
from my_daily_ui import MyDailyWindow,load_favorites,WEEKLY_PAGES
from my_daily_queue import ModuleQueue

class MyWeeklyWindow(MyDailyWindow):
    TITLE='我的周常'
    def __init__(self,app,path=None):
        self.app=app;daily=app.my_daily_window
        self.pages={title:keys for title,keys in daily.full_pages.items() if title in WEEKLY_PAGES}
        keys={k for group in self.pages.values() for k in group}
        self.catalog={k:row for k,row in daily.full_catalog.items() if k in keys}
        self.modules={k:row for k,row in daily.full_modules.items() if k in keys}
        self.path=Path(path) if path else Path(__file__).resolve().parent/'my_weekly_favorites.json'
        self.favorites=load_favorites(self.path,self.catalog)
        self.window=None;self.buttons=[];self.rows={};self.module_queue=ModuleQueue(self)
