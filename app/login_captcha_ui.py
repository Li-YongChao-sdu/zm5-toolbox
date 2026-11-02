"""人工验证码窗口；网络加载在后台，Tk控件只在主线程更新。"""
import base64,io,threading
import tkinter as tk
from tkinter import ttk

def ask_captcha(app,verification,loader):
    image_bytes=loader()
    done=threading.Event();answer=[None]
    def open_dialog():
        win=tk.Toplevel(app.root);win.title('登录验证码');win.transient(app.root);win.resizable(False,False)
        frame=ttk.Frame(win,padding=16);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='请输入下图中的验证码，确认后继续登录。').pack(anchor='w')
        image_label=ttk.Label(frame);image_label.pack(pady=10)
        value=tk.StringVar(master=win);entry=ttk.Entry(frame,textvariable=value,width=24);entry.pack(fill='x')
        status=tk.StringVar(master=win,value='');ttk.Label(frame,textvariable=status,wraplength=330).pack(anchor='w',pady=6)
        row=ttk.Frame(frame);row.pack(fill='x');busy=[False]
        def finish(text=None):
            answer[0]=text
            try:win.grab_release();win.destroy()
            finally:done.set()
        def destroyed(event):
            if event.widget==win:done.set()
        win.bind('<Destroy>',destroyed)
        def render(data):
            try:
                try:
                    from PIL import Image,ImageTk
                    im=Image.open(io.BytesIO(data));im.load();im.thumbnail((400,160));photo=ImageTk.PhotoImage(im,master=win)
                except ImportError:photo=tk.PhotoImage(master=win,data=base64.b64encode(data))
                image_label.configure(image=photo);image_label.image=photo
                status.set('');submit.configure(state='normal');entry.focus_set()
            except Exception:
                status.set('验证码图片无法显示，请刷新重试。');submit.configure(state='disabled')
        def confirm(event=None):
            if busy[0] or str(submit.cget('state'))=='disabled':return
            text=value.get().strip()
            if not text:status.set('请先填写验证码。');entry.focus_set();return
            finish(text)
        def refresh():
            if busy[0]:return
            busy[0]=True;value.set('');status.set('正在刷新验证码…');submit.configure(state='disabled');refresh_btn.configure(state='disabled')
            def load():
                try:data=loader();error=False
                except Exception:data=None;error=True
                def apply():
                    if done.is_set():return
                    busy[0]=False;refresh_btn.configure(state='normal')
                    if error:status.set('图片加载失败，请检查网络后刷新。')
                    else:render(data)
                if not done.is_set():
                    try:app.root.after(0,apply)
                    except (RuntimeError,tk.TclError):done.set()
            threading.Thread(target=load,daemon=True).start()
        refresh_btn=ttk.Button(row,text='换一张',command=refresh);refresh_btn.pack(side='left')
        ttk.Button(row,text='取消',command=finish).pack(side='right')
        submit=ttk.Button(row,text='确认登录',command=confirm);submit.pack(side='right',padx=6)
        win.protocol('WM_DELETE_WINDOW',finish);win.bind('<Escape>',lambda event:finish());entry.bind('<Return>',confirm)
        try:render(image_bytes);win.grab_set()
        except Exception:finish();raise
    app.root.after(0,open_dialog)
    done.wait()
    return answer[0]
