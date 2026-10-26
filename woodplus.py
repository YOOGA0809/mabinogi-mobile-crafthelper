"""Windows foreground crafting helper. See README.md before use."""
import ctypes
from ctypes import wintypes
import json
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import messagebox

user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.SetProcessDPIAware()
def foreground():
    return int(user32.GetForegroundWindow() or 0)
def window_at(pos):
    h = user32.WindowFromPoint(wintypes.POINT(*pos))
    return int(user32.GetAncestor(h, 2) or 0)
def window_title(h):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(h, buf, 256)
    return buf.value

import pyautogui as pg
from PIL import ImageChops, ImageStat
from pynput import keyboard

pg.FAILSAFE = True
pg.PAUSE = .15
BASE = Path(__file__).resolve().parent
CFG = BASE / 'settings.json'
config = json.loads(CFG.read_text('utf-8')) if CFG.exists() else {}
stop = threading.Event()
worker = None
root = tk.Tk()
root.title('瑪奇 Mobile 木材＋助手（前景試用版）')
root.geometry('580x570')
status = tk.StringVar(value='先閱讀 README；首次使用請依序校正。')
logs = []
def log(s):
    logs.append(time.strftime('%H:%M:%S ') + s)
    root.after(0, status.set, s)
    (BASE / 'run.log').write_text('\n'.join(logs), 'utf-8')
def save():
    CFG.write_text(json.dumps(config, ensure_ascii=False, indent=2), 'utf-8')
def patch(pos):
    return pg.screenshot(region=(pos[0]-10, pos[1]-10, 20, 20)).convert('RGB')
def matches(im, ref, tolerance=16):
    return sum(ImageStat.Stat(ImageChops.difference(im, ref)).mean)/3 < tolerance

def calibrate(key, instruction, capture=False):
    if worker and worker.is_alive():
        return
    messagebox.showinfo('校正', instruction + '\n按確定後有 5 秒，把滑鼠移到指定位置，不要點擊。')
    root.iconify()
    def done():
        p = list(pg.position())
        config[key] = p
        if capture:
            patch(p).save(BASE / (key + '.png'))
        if key == 'wood':
            config['hwnd'] = foreground()
            config['screen'] = list(pg.size())
        save()
        root.deiconify()
        status.set('已記錄：' + key)
    root.after(5000, done)

instructions = [
 ('wood','1. 木材卡片＋主畫面辨識','關閉右下配方視窗，移到第一格木材圖示中央。',True),
 ('plus','2. 木材＋卡片','關閉右下配方視窗，移到第二格木材＋卡片中央。',False),
 ('disabled','3. 不能加工按鈕的顏色（新版必做）','開啟任一材料不足的配方，確認加工按鈕呈固定暗藍色。移到按鈕左側內部中央，距離邊緣至少 20 像素，避開文字、星號及圓角。',True),
 ('dismiss','4. 關閉配方的位置','開啟配方後，移到畫面正中央無按鈕的空白處（點此處應能關閉配方）。',False),
]
for key,label,instruction,capture in instructions:
    tk.Button(root,text=label,command=lambda k=key,i=instruction,c=capture:calibrate(k,i,c)).pack(fill='x',padx=15,pady=3)
frame=tk.Frame(root);frame.pack(pady=8)
wood_time=tk.StringVar(value=str(config.get('wood_seconds',60)))
plus_time=tk.StringVar(value=str(config.get('plus_seconds',390)))
for col,title,var in [(0,'木材等待秒數',wood_time),(1,'木材＋等待秒數',plus_time)]:
    tk.Label(frame,text=title).grid(row=0,column=col)
    tk.Entry(frame,textvariable=var,width=20).grid(row=1,column=col)

def check():
    if stop.is_set():
        raise RuntimeError('已停止；重開前先領取成品、清空佇列。')
    if foreground() != config['hwnd']:
        raise RuntimeError('遊戲已失去焦點，停止。目前前景：' + window_title(foreground()) + '；請切回遊戲按 F8。')
    if list(pg.size()) != config['screen']:
        raise RuntimeError('螢幕尺寸改變，請重新校正。')
def wait(seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        check()
        time.sleep(.1)
def click(key):
    check();pg.click(*config[key]);wait(.8)
def press_space():
    check()
    pg.press('space')
    wait(.8)

def main_screen():
    check()
    return matches(patch(config['wood']), reference)
def require_main():
    if not main_screen():
        raise RuntimeError('畫面不符合木材加工主畫面，停止，請檢查。')
def collect_results():
    require_main()
    log('按空白鍵領取成品。')
    press_space()
    wait(1.2)  # Allow the crafting-completed animation to finish.
    log('再按一次空白鍵，確認加工完成視窗。')
    press_space()
    for _ in range(15):
        if main_screen():
            log('已領取並返回加工主畫面。')
            return
        wait(.2)
    raise RuntimeError('確認後仍未返回加工主畫面，停止，請檢查結果視窗。')

def attempt(kind):
    require_main()
    click(kind)
    if main_screen():
        raise RuntimeError('點選配方後未出現視窗，停止。')
    check()
    if matches(patch(config['disabled']), disabled_reference, tolerance=12):
        log('辨識到不能加工的固定暗藍樣式，略過此配方。')
        click('dismiss');require_main()
        return False
    log('未符合不能加工樣式，按空白鍵嘗試加工。')
    press_space()
    require_main()  # Successful submission must close the recipe popup.
    log('已送出：' + ('木材＋' if kind=='plus' else '木材'))
    wait(config['plus_seconds'] if kind=='plus' else config['wood_seconds'])
    collect_results()
    return True

def run(from_game=False):
    global reference,disabled_reference
    try:
        reference=__import__('PIL.Image',fromlist=['open']).open(BASE/'wood.png').convert('RGB')
        disabled_reference=__import__('PIL.Image',fromlist=['open']).open(BASE/'disabled.png').convert('RGB')
        # Countdown permits manual switching to the game; no automated focus stealing.
        log('2 秒後開始，請保持遊戲前景。' if from_game else '5 秒後開始，請切回遊戲木材加工主畫面。')
        if stop.wait(2 if from_game else 5): return
        target = window_at(config['wood'])
        current = foreground()
        if not target or target != current:
            raise RuntimeError('未切回校正位置的遊戲視窗。目前前景：' + window_title(current) + '。請切回遊戲按 F8。')
        config['hwnd'] = target
        log('已重新綁定視窗：' + window_title(target))
        require_main()
        while True:
            if attempt('plus'):
                continue
            log('木材＋暫不可加工，嘗試補一批木材。')
            if not attempt('wood'):
                log('兩種配方均無法加工，結束。請確認剩餘原料。');break
            if not attempt('plus'):
                log('補完木材仍不能做木材＋，停止：請檢查樹液或畫面校正。');break
    except Exception as e:
        log(str(e))
    finally:
        stop.set()

def start(from_game=False):
    global worker
    if worker and worker.is_alive(): return
    if not all(k in config for k,_,_,_ in instructions) or 'hwnd' not in config:
        messagebox.showerror('尚未校正','請完成四項校正。舊版更新只需重做第 3 項：不能加工按鈕。');return
    try:
        w=float(wood_time.get());p=float(plus_time.get())
        if w<45 or p<360 or w>86400 or p>86400: raise ValueError()
    except ValueError:
        messagebox.showerror('等待時間','木材至少 45 秒、木材＋至少 360 秒，最多 86400 秒。');return
    if not from_game and not messagebox.askokcancel('開始前確認','已清空全部 5 格加工佇列，且停在木材加工主畫面？\n等待值須大於你實際的一次加工時間。\n執行期間遊戲必須保持前景。'):
        return
    config.update(wood_seconds=w,plus_seconds=p);save();stop.clear()
    worker=threading.Thread(target=run,args=(from_game,),daemon=True);worker.start()
def halt():
    stop.set()
    status.set('停止中；再次開始前先領取並清空全部加工佇列。')
tk.Button(root,text='開始（5 秒內切回遊戲；也可直接在遊戲按 F8）',command=start).pack(fill='x',padx=15,pady=5)
tk.Button(root,text='停止（F10）',command=halt).pack(fill='x',padx=15)
tk.Label(root,textvariable=status,wraplength=545,justify='left').pack(pady=12)
tk.Label(root,text='僅使用一格佇列；勿移動視窗、改縮放或遮住遊戲。\nF8 開始／F10 停止／滑鼠移至主螢幕左上角緊急停止。').pack()
pressed = set()
def on_key(key):
    if key in pressed:
        return
    pressed.add(key)
    if key==keyboard.Key.f8:
        root.after(0, lambda: start(True))
    if key==keyboard.Key.f10:
        stop.set()
def on_release(key):
    pressed.discard(key)
listener=keyboard.Listener(on_press=on_key,on_release=on_release);listener.start()
root.protocol('WM_DELETE_WINDOW',lambda:(stop.set(),root.destroy()))
root.mainloop()
