import unittest
from copy import deepcopy
from craft_core import DEFAULT, Runner, validate, card_position

class IO:
    def __init__(self,states=None,disabled=None):
        self.events=[];self.states=list(states or []);self.flags=list(disabled or []);self.present=True
    def wait(self,s):self.events.append(('wait',s))
    def key(self,k):self.events.append(('key',k))
    def click(self,x,y):self.events.append(('click',x,y))
    def capture_header(self):return 'header'
    def header_present(self):return self.present
    def page_matches(self,ref):return self.states.pop(0) if self.states else True
    def disabled(self,l):return self.flags.pop(0) if self.flags else False

class Tests(unittest.TestCase):
    def setUp(self):self.config=deepcopy(DEFAULT)
    def test_coordinates(self):
        self.assertEqual(card_position(self.config,1),(604,250))
        self.assertEqual(card_position(self.config,2),(748,250))
        self.assertEqual(card_position(self.config,8),(604,460))
    def test_navigation(self):
        io=IO([True,False,False,True,True,True,True]);r=Runner(self.config,io);r.navigate(2)
        self.assertEqual([e[1] for e in io.events if e[0]=='key'],['k','w','w','w','s'])
        self.assertIn(('click',580,280),io.events)
        self.assertIn(('click',156,213),io.events)
    def test_no_arrival_no_crafting(self):
        io=IO();r=Runner(self.config,io)
        with self.assertRaisesRegex(RuntimeError,'逾時'):r.run('wood_plus',1)
        self.assertNotIn(('key','space'),io.events)
    def test_missing_preview(self):
        io=IO();io.present=False
        with self.assertRaisesRegex(RuntimeError,'預覽'):Runner(self.config,io).navigate(1)
        self.assertNotIn(('click',156,213),io.events)
    def test_success_and_result_confirmation(self):
        # Main, modal, submitted-main, collect-main, confirmed-main.
        io=IO([True,False,True,True,True]);r=Runner(self.config,io);r.header='header'
        self.assertTrue(r.attempt(self.config['recipes'][0]))
        self.assertEqual(io.events.count(('key','space')),3)
        self.assertEqual(r.completed['wood'],1)
        self.assertIn(('wait',60),io.events)
    def test_disabled_never_sends_space(self):
        io=IO([True,False,True],[True]);r=Runner(self.config,io);r.header='header'
        self.assertFalse(r.attempt(self.config['recipes'][0]))
        self.assertNotIn(('key','space'),io.events)
    def test_missing_modal_stops(self):
        io=IO([True,True]);r=Runner(self.config,io);r.header='header'
        with self.assertRaisesRegex(RuntimeError,'配方視窗'):r.attempt(self.config['recipes'][0])
        self.assertNotIn(('key','space'),io.events)
    def test_result_timeout_stops_without_repeating_keys(self):
        io=IO([True,False,True,True]+[False]*20);r=Runner(self.config,io);r.header='header'
        with self.assertRaisesRegex(RuntimeError,'未返回'):r.attempt(self.config['recipes'][0])
        self.assertEqual(io.events.count(('key','space')),3)
        self.assertEqual(r.completed['wood'],0)
    def test_stop_aborts_before_first_key(self):
        io=IO()
        def stop(k):raise RuntimeError('stopped')
        io.key=stop
        with self.assertRaisesRegex(RuntimeError,'stopped'):Runner(self.config,io).run('wood',1)
    def test_manual_recipe(self):
        self.config['recipes'].append({'id':'iron','name':'鐵錠','station':1,'slot':1,'seconds':60,'yield':3,'precursor':''})
        validate(self.config)
    def test_cycle(self):
        self.config['recipes'][0]['precursor']='wood_plus'
        with self.assertRaisesRegex(ValueError,'循環'):validate(self.config)
    def test_cross_station_rejected(self):
        self.config['recipes'][0]['station']=1
        with self.assertRaisesRegex(ValueError,'同一加工台'):validate(self.config)
    def test_duplicate_slot(self):
        self.config['recipes'][1]['slot']=1
        with self.assertRaisesRegex(ValueError,'重複'):validate(self.config)
    def test_nonfinite_time(self):
        self.config['recipes'][0]['seconds']=float('nan')
        with self.assertRaises(ValueError):validate(self.config)
    def test_precursor_retry_is_bounded(self):
        r=Runner(self.config,IO());called=[];answers=iter([False,True,False])
        def attempt(recipe):called.append(recipe['id']);return next(answers)
        r.attempt=attempt
        self.assertFalse(r.produce('wood_plus'))
        self.assertEqual(called,['wood_plus','wood','wood_plus'])
    def test_batches_count_only_target(self):
        r=Runner(self.config,IO());r.navigate=lambda station:None
        called=[];r.produce=lambda rid:called.append(rid) or True
        self.assertEqual(r.run('wood_plus',2),2)
        self.assertEqual(called,['wood_plus','wood_plus'])
    def test_unlimited_stops_on_unavailable(self):
        r=Runner(self.config,IO());r.navigate=lambda station:None
        answers=iter([True,False]);r.produce=lambda rid:next(answers)
        self.assertEqual(r.run('wood_plus',0),1)

if __name__=='__main__':unittest.main()
