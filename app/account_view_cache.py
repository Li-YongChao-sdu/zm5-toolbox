"""切换账号/存档时丢弃服务器状态，保留用户填写的运行设置。"""
import tkinter as tk
from tkinter import ttk

PAGES=('card_cave_target_page','maze_target_controls','stove_page','pet_mating_page',
       'pet_utility_page','black_market_page','bag_warehouse_page','material_exchange_page','mail_page')
STATUS_VARS=('summary','status','card_status','shop_status','photo_summary','album_summary','last_photo','cost','rank_summary')

def clear_widgets(widget):
    if isinstance(widget,ttk.Treeview):widget.delete(*widget.get_children())
    elif isinstance(widget,tk.Text):
        state=str(widget.cget('state'));widget.configure(state='normal');widget.delete('1.0','end');widget.configure(state=state)
    for child in widget.winfo_children():clear_widgets(child)

def invalidate(app):
    app._account_view_epoch=getattr(app,'_account_view_epoch',0)+1
    forest_controls=getattr(app,'forest_crystal_controls',None)
    if forest_controls is not None:forest_controls.invalidate()
    time_panel=getattr(app,'time_crystal_panel',None)
    if time_panel is not None:time_panel.invalidate()
    feed_panel=getattr(app,'fairy_feed_panel',None)
    if feed_panel is not None:feed_panel.invalidate()
    fashion_panel=getattr(app,'fashion_online_panel',None)
    if fashion_panel is not None:fashion_panel.invalidate()
    message='账号或存档已切换，请重新查询当前存档；次数和余额尚未读取。'
    for name in PAGES:
        page=getattr(app,name,None)
        if page is None:continue
        if hasattr(page,'invalidate'):page.invalidate()
        for key in ('data','rank_data'): 
            if hasattr(page,key):setattr(page,key,None)
        for key in ('rows','rank_rows','pets','targets','sources','visible'):
            if isinstance(getattr(page,key,None),dict):setattr(page,key,{})
        if hasattr(page,'active_tree'):page.active_tree=None
        for key in STATUS_VARS:
            var=getattr(page,key,None)
            if isinstance(var,tk.Variable):var.set(message)
        for row in getattr(page,'shop_rows',{}).values():
            for key in ('used','remaining'):
                if key in row:row[key].set('未查询')
            if 'count' in row:row['count'].set('0')
        if hasattr(page,'card_count'):page.card_count.set('0')
        widget=getattr(page,'page',None) or getattr(page,'parent',None)
        if widget is not None:clear_widgets(widget)
    if hasattr(app,'union_summary'):app.union_summary.set(message)
    if hasattr(app,'union_stock'):clear_widgets(app.union_stock)

def current(epoch,app):
    return epoch is None or epoch==getattr(app,'_account_view_epoch',0)
