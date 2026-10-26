"""Windows foreground processing helper; run start.bat. See README.md."""
import ctypes
from ctypes import wintypes
from copy import deepcopy
import json
import math
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from craft_core import DEFAULT, STATIONS, Runner, validate

BASE=Path(__file__).resolve().parent
CONFIG=BASE/'craft_config.json'
LABELS={
 'station_first_x':'加工台1中心 X','station_y':'加工台中心 Y','station_gap':'加工台橫向間距',
 'card_first_x':'材料1中心 X','card_first_y':'材料1中心 Y','card_gap_x':'材料橫向間距',
 'card_gap_y':'材料縱向間距','card_columns':'每列材料張數','go_x':'前往設備 X','go_y':'前往設備 Y',
 'dismiss_x':'關閉配方空白處 X','dismiss_y':'關閉配方空白處 Y',
 'disabled_x':'不能加工取樣 X','disabled_y':'不能加工取樣 Y','disabled_r':'暗藍色 R',
 'disabled_g':'暗藍色 G','disabled_b':'暗藍色 B','travel_timeout':'抵達設備逾時（秒）',
 'key_delay':'切頁按鍵間隔（秒）','result_delay':'領取結果等待（秒）'}

def main():
    if sys.platform!='win32':raise SystemExit('此程式需要 Windows。')
    user32=ctypes.windll.user32
    user32.SetProcessDPIAware()
    user32.GetForegroundWindow.restype=wintypes.HWND
    user32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user32.GetClientRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.POINT)]
    import pyautogui as pg
    from PIL import ImageChops,ImageStat
    from pynput import keyboard
    pg.FAILSAFE=True;pg.PAUSE=.12
    root=tk.Tk();root.title('瑪奇 Mobile 加工助手 v2');root.geometry('1000x740')
    try:
        config=json.loads(CONFIG.read_text('utf-8')) if CONFIG.exists() else deepcopy(DEFAULT)
        validate(config)
    except Exception as exc:
        messagebox.showerror('設定無法讀取','請保留設定檔並修正錯誤：'+str(exc));root.destroy();return
    events=queue.Queue();stop=threading.Event();worker=None;closing=False
    status=tk.StringVar(value='請先關閉遊戲所有頁面，清空加工佇列，再切回遊戲按 F8。')
    selected=tk.StringVar();batch=tk.StringVar(value='0')
    tabs=ttk.Notebook(root);tabs.pack(fill='both',expand=True,padx=10,pady=10)
    run_tab=ttk.Frame(tabs);recipes_tab=ttk.Frame(tabs);layout_tab=ttk.Frame(tabs)
    for frame,name in [(run_tab,'執行'),(recipes_tab,'配方管理'),(layout_tab,'共用版面')]:tabs.add(frame,text=name)
    def log(text):events.put(('log',text))
    def busy():return worker is not None and worker.is_alive()
    def save():
        validate(config)
        tmp=CONFIG.with_suffix('.tmp');tmp.write_text(json.dumps(config,ensure_ascii=False,indent=2),'utf-8');tmp.replace(CONFIG)
    ttk.Label(run_tab,text='開始前：關閉全部遊戲頁面、加工佇列清空，篩選為「全部」且清單置頂。').pack(anchor='w',padx=14,pady=14)
    ttk.Label(run_tab,text='本版每次執行一個加工台；前置材料需在同台。F8 開始／F10 停止。').pack(anchor='w',padx=14)
    ttk.Label(run_tab,text='製作目標').pack(anchor='w',padx=14,pady=(20,3))
    combo=ttk.Combobox(run_tab,textvariable=selected,state='readonly',width=65);combo.pack(anchor='w',padx=14)
    ttk.Label(run_tab,text='目標批次（0＝做到缺料；每批產量僅供參考，不辨識大成功）').pack(anchor='w',padx=14,pady=(15,3))
    ttk.Entry(run_tab,textvariable=batch,width=15).pack(anchor='w',padx=14)
    ttk.Label(run_tab,textvariable=status,wraplength=900).pack(anchor='w',padx=14,pady=14)
    output=tk.Text(run_tab,height=19,state='disabled',wrap='word');output.pack(fill='both',expand=True,padx=14,pady=8)

    class IO:
        def __init__(self,hwnd):
            self.hwnd=hwnd
            title=ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd,title,512)
            if '瑪奇' not in title.value and 'mabinogi' not in title.value.lower():
                raise RuntimeError('目前前景不是瑪奇遊戲視窗，未送出按鍵：'+title.value)
            self.initial=self.geometry()
            _,_,w,h=self.initial
            if abs(w/h-16/9)>.08:raise RuntimeError('請使用接近 16:9 的遊戲視窗，或調整共用版面設定。')
        def geometry(self):
            rect=wintypes.RECT();point=wintypes.POINT(0,0)
            if not user32.GetClientRect(self.hwnd,ctypes.byref(rect)) or not user32.ClientToScreen(self.hwnd,ctypes.byref(point)):raise RuntimeError('無法取得遊戲視窗。')
            if rect.right<=0 or rect.bottom<=0:raise RuntimeError('遊戲視窗不可最小化。')
            return point.x,point.y,rect.right,rect.bottom
        def check(self):
            if stop.is_set():raise RuntimeError('已停止。再次開始前請清空佇列並關閉所有遊戲頁面。')
            if int(user32.GetForegroundWindow() or 0)!=self.hwnd:raise RuntimeError('遊戲失去焦點，已停止。')
            if self.geometry()!=self.initial:raise RuntimeError('遊戲視窗位置或尺寸改變，已停止。')
        def wait(self,seconds):
            end=time.monotonic()+seconds
            while time.monotonic()<end:self.check();time.sleep(min(.1,max(0,end-time.monotonic())))
        def point(self,x,y):
            ox,oy,w,h=self.initial
            if not 0<=x<1920 or not 0<=y<1080:raise RuntimeError('點擊座標超出共用版面。')
            return round(ox+x*w/1920),round(oy+y*h/1080)
        def click(self,x,y):self.check();pg.click(*self.point(x,y))
        def key(self,key):self.check();pg.press(key)
        def capture(self,x,y,w,h):
            self.check();sx,sy=self.point(x,y);ex,ey=self.point(x+w,y+h)
            return pg.screenshot(region=(sx,sy,max(1,ex-sx),max(1,ey-sy))).convert('RGB')
        def capture_header(self):return self.capture(20,18,330,45)
        def header_present(self):
            im=self.capture_header();pixels=list(im.getdata())
            return sum(min(p)>175 for p in pixels)/len(pixels)>.008
        def page_matches(self,ref):
            current=self.capture_header()
            return sum(ImageStat.Stat(ImageChops.difference(current,ref)).mean)/3<10
        def disabled(self,layout):
            im=self.capture(layout['disabled_x']-8,layout['disabled_y']-8,16,16)
            mean=ImageStat.Stat(im).mean
            expected=[layout['disabled_r'],layout['disabled_g'],layout['disabled_b']]
            return sum(abs(a-b) for a,b in zip(mean,expected))/3<12

    def start(hwnd=None):
        nonlocal worker
        if busy():return
        try:
            save()
            names=recipe_options();index=names.index(selected.get());recipe_id=config['recipes'][index]['id']
            count=int(batch.get())
            if count<0:raise ValueError('批次不可小於 0')
            # The hotkey captures the foreground HWND without bringing this GUI forward.
            if not hwnd:
                messagebox.showinfo('開始','按確定後 5 秒內切回遊戲。請確定已關閉所有頁面並清空加工佇列。')
            snapshot=deepcopy(config)
        except Exception as exc:messagebox.showerror('無法開始',str(exc));return
        stop.clear()
        def work():
            try:
                log('即將開始，請保持遊戲前景。')
                if stop.wait(2 if hwnd else 5):return
                target=hwnd or int(user32.GetForegroundWindow() or 0)
                own=int(root.winfo_id())
                if target==own:raise RuntimeError('請先切回遊戲。')
                io=IO(target);io.check();Runner(snapshot,io,log).run(recipe_id,count)
            except Exception as exc:log(str(exc))
            finally:stop.set()
        worker=threading.Thread(target=work,daemon=True);worker.start()
    ttk.Button(run_tab,text='開始（5 秒內切回遊戲）',command=start).pack(side='left',padx=14,pady=8)
    ttk.Button(run_tab,text='停止 F10',command=stop.set).pack(side='left',padx=5,pady=8)
    def recipe_options():return [f"{r['name']} 〔加工台 {r['station']}／位置 {r['slot']}〕" for r in config['recipes']]
    tree=ttk.Treeview(recipes_tab,columns=('id','name','station','slot','seconds','yield','precursor'),show='headings',height=12)
    for key,label,width in [('id','ID',120),('name','名稱',140),('station','加工台',90),('slot','材料編號',90),('seconds','等待秒數',100),('yield','每批產量',90),('precursor','缺料補做 ID',140)]:tree.heading(key,text=label);tree.column(key,width=width)
    tree.pack(fill='both',expand=True,padx=10,pady=10)
    ttk.Label(recipes_tab,text='加工台：'+ '　'.join(f'{i+1} {n}' for i,n in enumerate(STATIONS)),wraplength=930).pack(anchor='w',padx=10)
    form=ttk.Frame(recipes_tab);form.pack(fill='x',padx=10,pady=10)
    fields={}
    for i,(key,label) in enumerate([('id','唯一 ID'),('name','名稱'),('station','加工台編號 1–6'),('slot','材料卡片編號'),('seconds','等待秒數（含緩衝）'),('yield','每批產量'),('precursor','前置 ID（可留空）')]):
        row,col=divmod(i,4);ttk.Label(form,text=label).grid(row=row*2,column=col,sticky='w',padx=6)
        var=tk.StringVar();fields[key]=var;ttk.Entry(form,textvariable=var,width=23).grid(row=row*2+1,column=col,padx=6,pady=4)
    def refresh():
        old=selected.get();opts=recipe_options();combo['values']=opts
        if old in opts:selected.set(old)
        else:selected.set(opts[0] if opts else '')
        tree.delete(*tree.get_children())
        for r in config['recipes']:tree.insert('', 'end',iid=r['id'],values=tuple(r[k] for k in fields))
    def load_selected(event=None):
        if not tree.selection():return
        r=next(r for r in config['recipes'] if r['id']==tree.selection()[0])
        for k,var in fields.items():var.set(str(r[k]))
    tree.bind('<<TreeviewSelect>>',load_selected)
    def apply_recipe():
        if busy():messagebox.showwarning('執行中','請先停止再修改配方。');return
        old=deepcopy(config)
        try:
            r={k:var.get().strip() for k,var in fields.items()}
            for k in ['station','slot','yield']:r[k]=int(r[k])
            r['seconds']=float(r['seconds'])
            existing=next((i for i,x in enumerate(config['recipes']) if x['id']==r['id']),None)
            if existing is None:config['recipes'].append(r)
            else:config['recipes'][existing]=r
            save();refresh()
        except Exception as exc:config.clear();config.update(old);messagebox.showerror('配方錯誤',str(exc))
    def delete_recipe():
        if busy() or not tree.selection():return
        rid=tree.selection()[0]
        if any(r['precursor']==rid for r in config['recipes']):messagebox.showerror('無法刪除','此配方仍被其他配方當作前置材料。');return
        if not messagebox.askyesno('刪除配方','刪除 '+rid+'？'):return
        config['recipes']=[r for r in config['recipes'] if r['id']!=rid];save();refresh()
    buttons=ttk.Frame(recipes_tab);buttons.pack(anchor='w',padx=10,pady=8)
    ttk.Button(buttons,text='新增／更新（相同 ID 更新）',command=apply_recipe).pack(side='left',padx=4)
    ttk.Button(buttons,text='清空欄位',command=lambda:[v.set('') for v in fields.values()]).pack(side='left',padx=4)
    ttk.Button(buttons,text='刪除所選配方',command=delete_recipe).pack(side='left',padx=4)
    ttk.Label(layout_tab,text='座標以遊戲內容區 1920×1080 為基準，程式按視窗比例換算。不同介面縮放請在此修改一次。\n卡片由左到右、由上到下編號。清單須置頂且篩選為「全部」；本版不自動捲動。',wraplength=930).pack(anchor='w',padx=12,pady=12)
    layout_form=ttk.Frame(layout_tab);layout_form.pack(padx=12,pady=8)
    layout_vars={}
    for i,key in enumerate(DEFAULT['layout']):
        row,col=divmod(i,4);var=tk.StringVar(value=str(config['layout'][key]));layout_vars[key]=var
        ttk.Label(layout_form,text=LABELS[key]).grid(row=row*2,column=col,sticky='w',padx=8)
        ttk.Entry(layout_form,textvariable=var,width=23).grid(row=row*2+1,column=col,padx=8,pady=4)
    def save_layout():
        if busy():messagebox.showwarning('執行中','請先停止再修改版面。');return
        old=deepcopy(config['layout'])
        try:
            config['layout']={k:float(v.get()) for k,v in layout_vars.items()};save();messagebox.showinfo('完成','已儲存共用版面。')
        except Exception as exc:config['layout']=old;messagebox.showerror('版面錯誤',str(exc))
    ttk.Button(layout_tab,text='儲存共用版面',command=save_layout).pack(anchor='w',padx=12,pady=10)
    refresh()
    pressed=set()
    def on_press(key):
        if key in pressed:return
        pressed.add(key)
        if key==keyboard.Key.f10:stop.set()
        elif key==keyboard.Key.f8:events.put(('start',int(user32.GetForegroundWindow() or 0)))
    def on_release(key):pressed.discard(key)
    listener=keyboard.Listener(on_press=on_press,on_release=on_release);listener.start()
    def pump():
        if closing:return
        try:
            while True:
                kind,value=events.get_nowait()
                if kind=='start':start(value)
                else:
                    status.set(value);line=time.strftime('%H:%M:%S ')+value+'\n'
                    output.configure(state='normal');output.insert('end',line);output.see('end');output.configure(state='disabled')
                    with (BASE/'run.log').open('a',encoding='utf-8') as file:file.write(line)
        except queue.Empty:pass
        root.after(100,pump)
    def close():
        nonlocal closing
        closing=True;stop.set();listener.stop();root.destroy()
    root.protocol('WM_DELETE_WINDOW',close);pump();root.mainloop()

if __name__=='__main__':main()
