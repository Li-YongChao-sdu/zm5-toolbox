from tkinter import ttk

def select_page(app,title):
    """查找收纳后的嵌套页，依次展开父标签。"""
    wanted=title
    def find(notebook):
        for tab in notebook.tabs():
            page=notebook.nametowidget(tab)
            if notebook.tab(tab,'text')==wanted:
                notebook.select(tab);return True
            def below(widget):
                for child in widget.winfo_children():
                    if isinstance(child,ttk.Notebook) and find(child):return True
                    if not isinstance(child,ttk.Notebook) and below(child):return True
                return False
            if below(page):notebook.select(tab);return True
        return False
    return find(app.main_notebook)
