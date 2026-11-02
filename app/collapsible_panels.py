"""给现有LabelFrame增加可点击标题；不搬动控件或改动变量绑定。"""
from tkinter import ttk

class CollapsiblePanel:
    def __init__(self,frame,collapsed=True):
        self.frame=frame;self.title=str(frame.cget('text'));self.collapsed=False;self.saved=[]
        self.height=frame.cget('height');self.width=frame.cget('width')
        self.pack_propagate=frame.pack_propagate();self.grid_propagate=frame.grid_propagate()
        self.header=ttk.Frame(frame)
        self.button=ttk.Button(self.header,text='▾ '+self.title,command=self.toggle)
        self.button.pack(side='left');frame.configure(labelwidget=self.header)
        if collapsed:self.set_collapsed(True)
    def toggle(self):self.set_collapsed(not self.collapsed)
    def set_collapsed(self,value):
        value=bool(value)
        if self.collapsed==value:return
        if value:
            self.saved=[]
            for child in self.frame.winfo_children():
                if child==self.header:continue
                manager=child.winfo_manager()
                if manager in ('pack','grid','place'):
                    info=getattr(child,manager+'_info')();self.saved.append((child,manager,info))
                    getattr(child,manager+'_forget')()
            self.frame.pack_propagate(False);self.frame.grid_propagate(False)
            self.frame.configure(height=max(32,self.button.winfo_reqheight()+8),width=1)
        else:
            self.frame.configure(height=self.height,width=self.width)
            self.frame.pack_propagate(self.pack_propagate);self.frame.grid_propagate(self.grid_propagate)
            for child,manager,info in self.saved:
                if child.winfo_exists():getattr(child,manager)(**info)
            self.saved=[]
        self.collapsed=value;self.button.configure(text=('▸ ' if value else '▾ ')+self.title)

def install(parent):
    frames=[]
    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child,ttk.LabelFrame):frames.append(child)
            walk(child)
    walk(parent);panels=[]
    for frame in frames:
        if getattr(frame,'_collapse_adapter',None) is not None:continue
        expanded = bool(getattr(frame, '_default_expanded', False)) or str(frame.cget('text')) == '执行项目'
        panel=CollapsiblePanel(frame,collapsed=not expanded)
        frame._collapse_adapter=panel;panels.append(panel)
    return panels
