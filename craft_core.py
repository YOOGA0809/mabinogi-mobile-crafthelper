"""Recipe configuration and foreground workflow, independent of Windows/Tk."""
from copy import deepcopy
import math

STATIONS = ['金屬加工', '木材加工', '皮革加工', '布料加工', '藥品加工', '食材加工']
DEFAULT = {
 'version': 2,
 'layout': {'station_first_x':291,'station_y':280,'station_gap':289,
 'card_first_x':604,'card_first_y':250,'card_gap_x':144,'card_gap_y':210,'card_columns':7,
 'go_x':156,'go_y':213,'dismiss_x':960,'dismiss_y':450,
 'disabled_x':1470,'disabled_y':1018,'disabled_r':32,'disabled_g':98,'disabled_b':120,
 'travel_timeout':90,'key_delay':0.35,'result_delay':2},
 'recipes': [
 {'id':'wood','name':'木材','station':2,'slot':1,'seconds':60,'yield':3,'precursor':''},
 {'id':'wood_plus','name':'木材＋','station':2,'slot':2,'seconds':390,'yield':3,'precursor':'wood'}]
}

def validate(config):
    layout=config['layout']
    for key,default in DEFAULT['layout'].items():
        value=layout[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError('版面設定必須是有限數字：'+key)
    for key in ['card_columns']:
        if int(layout[key]) != layout[key] or layout[key]<1: raise ValueError('每列張數須為正整數')
    for key in ['card_gap_x','card_gap_y','station_gap','travel_timeout','key_delay','result_delay']:
        if layout[key]<=0: raise ValueError('間距與等待秒數必須大於 0：'+key)
    for key in ['disabled_r','disabled_g','disabled_b']:
        if not 0<=layout[key]<=255: raise ValueError('RGB 必須介於 0 與 255')
    ids=set();positions=set()
    for r in config['recipes']:
        if not r['id'] or r['id'] in ids: raise ValueError('配方 ID 不可空白或重複')
        ids.add(r['id'])
        if not r['name'].strip(): raise ValueError('名稱不可空白')
        for k in ['station','slot','yield']:
            if isinstance(r[k],bool) or not isinstance(r[k],int) or r[k]<1: raise ValueError('加工台、位置與產量須為正整數')
        if r['station']>6: raise ValueError('加工台編號須介於 1 至 6')
        if not math.isfinite(r['seconds']) or r['seconds']<=0: raise ValueError('等待時間須大於 0')
        pos=(r['station'],r['slot'])
        if pos in positions: raise ValueError('同一加工台的材料位置不可重複')
        positions.add(pos)
    lookup={r['id']:r for r in config['recipes']}
    for r in config['recipes']:
        seen=set();node=r
        while node['precursor']:
            if node['id'] in seen: raise ValueError('前置配方不能循環')
            seen.add(node['id'])
            if node['precursor'] not in lookup: raise ValueError('找不到前置配方：'+node['precursor'])
            child=lookup[node['precursor']]
            if child['station']!=r['station']: raise ValueError('本版前置配方須位於同一加工台')
            node=child
    for r in config['recipes']:
        x,y=card_position(config,r['slot'])
        if not 0<x<1920 or not 0<y<1080: raise ValueError('材料位置超出畫面；請調整版面或編號')

def card_position(config,slot):
    l=config['layout'];row,col=divmod(slot-1,int(l['card_columns']))
    return l['card_first_x']+col*l['card_gap_x'],l['card_first_y']+row*l['card_gap_y']

class Runner:
    def __init__(self,config,io,log=lambda message:None):
        validate(config)
        self.config=deepcopy(config);self.io=io;self.log=log
        self.recipes={r['id']:r for r in config['recipes']};self.header=None
        self.completed={r['id']:0 for r in config['recipes']}
    def navigate(self,station):
        l=self.config['layout'];io=self.io
        self.log('開啟加工選單：K → W ×3 → S ×1')
        io.key('k');io.wait(1)
        for _ in range(3):io.key('w');io.wait(l['key_delay'])
        io.key('s');io.wait(l['key_delay'])
        io.click(l['station_first_x']+(station-1)*l['station_gap'],l['station_y']);io.wait(1)
        if not io.header_present(): raise RuntimeError('未出現加工台預覽頁，停止。請檢查選單與位置設定。')
        self.header=io.capture_header()
        self.log('前往設備，等待角色抵達並自動開啟加工頁。')
        io.click(l['go_x'],l['go_y'])
        # Preview and equipment screens look similar: MUST observe leaving first.
        left=False;stable=0
        for _ in range(max(1,int(l['travel_timeout']/.2))):
            same=io.page_matches(self.header)
            if not same:left=True;stable=0
            elif left:
                stable+=1
                if stable>=4:self.log('設備加工頁已開啟。');return
            io.wait(.2)
        raise RuntimeError('前往設備逾時，未確認頁面離開後重新開啟。停止，未送出加工。')
    def require_page(self):
        if not self.io.page_matches(self.header): raise RuntimeError('未處於預期加工頁，停止。')
    def await_page(self):
        for _ in range(20):
            if self.io.page_matches(self.header):return
            self.io.wait(.2)
        raise RuntimeError('操作後未返回加工頁，停止，請檢查畫面。')
    def attempt(self,recipe):
        l=self.config['layout'];io=self.io
        self.require_page();io.click(*card_position(self.config,recipe['slot']));io.wait(.8)
        if io.page_matches(self.header): raise RuntimeError('配方視窗未開啟，請檢查材料編號。')
        if io.disabled(l):
            io.click(l['dismiss_x'],l['dismiss_y']);io.wait(.8);self.await_page()
            self.log(recipe['name']+'不能加工。');return False
        io.key('space');io.wait(.8);self.await_page()
        self.log('加工中：'+recipe['name']+'，等待 '+str(recipe['seconds'])+' 秒')
        io.wait(recipe['seconds']);self.require_page()
        io.key('space');io.wait(l['result_delay'])
        io.key('space');io.wait(.8);self.await_page()
        self.completed[recipe['id']]+=1
        self.log(recipe['name']+' 已完成 '+str(self.completed[recipe['id']])+' 批（不含大成功數量辨識）')
        return True
    def produce(self,recipe_id):
        r=self.recipes[recipe_id]
        if self.attempt(r):return True
        if not r['precursor']:return False
        self.log('嘗試補做前置材料：'+self.recipes[r['precursor']]['name'])
        if not self.produce(r['precursor']):return False
        # A single optional precursor cannot identify other missing ingredients.
        if self.attempt(r):return True
        self.log('補做一批前置材料後仍不能加工，請檢查其他原料。');return False
    def run(self,recipe_id,batches=0):
        if recipe_id not in self.recipes:raise ValueError('請選擇配方')
        if not isinstance(batches,int) or batches<0:raise ValueError('目標批次須為非負整數')
        self.navigate(self.recipes[recipe_id]['station'])
        finished=0
        while not batches or finished<batches:
            if not self.produce(recipe_id):self.log('已停止：缺料或配方無法加工。');return finished
            finished+=1
        self.log('已達成目標批次。');return finished
