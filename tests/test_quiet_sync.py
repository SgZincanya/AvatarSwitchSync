from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
import avatar_sync as b
from test_runtime_050 import fixture


class QuietSyncTests(unittest.TestCase):
    def run_session(self,edit=False,switch=False):
        avatars,config,nodes,address=fixture()
        tick=[0.];reads=[];probes=[];sent=[];wakeups=[];edits=[False]
        class Stop:
            def is_set(self):return tick[0]>=60
            def wait(self,seconds):
                target=tick[0]+seconds
                for due,enabled,done in [(25,edit,edits[0]),(35,switch,transport.switched)]:
                    if enabled and not done and tick[0]<due<target:target=due
                wakeups.append(target);tick[0]=target;return self.is_set()
        class Transport:
            received_packets=sent_packets=0
            switched=False
            def changes(inner):
                if switch and tick[0]>=35 and not inner.switched:
                    inner.switched=True;nodes[address].update(TYPE='T',VALUE=[True]);return ['avtr_B']
                return []
            def identity(inner):probes.append(tick[0]);return 'avtr_B' if inner.switched else 'avtr_A'
            def snapshot(inner):reads.append(tick[0]);return ('avtr_B' if inner.switched else 'avtr_A'),nodes
            def take_updates(inner):
                if edit and tick[0]>=25 and not edits[0]:
                    edits[0]=True;nodes[address].update(TYPE='F',VALUE=[False]);return {address:('Bool',False)}
                return {}
            def send(inner,name,kind,value):
                sent.append((tick[0],name,value));nodes[address].update(TYPE='T' if value else 'F',VALUE=[value])
            def close(inner):pass
        transport=Transport()
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);b.write_json(data/'state.json',{'g':{'Accessory':{'type':'Bool','value':True}}})
            events=queue.Queue();worker=b.Worker(config,events,data,capture_current=False,add_group='g')
            worker.stop_event=Stop();worker.wait=worker.stop_event.wait
            with patch('avatar_sync.Transport',return_value=transport),patch('avatar_sync.inventory',return_value=avatars) as inventory,patch('avatar_sync.time.monotonic',side_effect=lambda:tick[0]),patch('parameter_snapshots.save_startup_backup',return_value={'id':'fixture'}):worker.run()
            state=b.read_json(data/'state.json',{})
            return reads,probes,sent,wakeups,list(events.queue),state,inventory.call_count

    def test_idle_does_not_reread_full_table_resend_or_refresh_unchanged_ui(self):
        reads,probes,sent,wakes,events,state,scans=self.run_session()
        self.assertTrue(reads);self.assertLess(max(reads),8)
        self.assertGreaterEqual(len(probes),8)
        self.assertEqual(len(sent),1)
        self.assertLess(len(wakes),40)
        self.assertLessEqual(scans,2)
        self.assertLessEqual(sum(k=='live' for k,v in events),4)
        self.assertEqual(sum(k=='diagnostics' for k,v in events),0)
        statuses=[v for k,v in events if k=='status'];self.assertEqual(len(statuses),len(set(statuses)))

    def test_notification_saves_edit_without_full_read_or_echo_and_switch_sends_new_value(self):
        reads,_,sent,_,_,state,_=self.run_session(edit=True,switch=True)
        self.assertFalse(any(8<t<35 for t in reads))
        self.assertEqual(len(sent),2)
        self.assertIs(sent[0][2],True);self.assertGreater(sent[1][0],35);self.assertIs(sent[1][2],False)
        self.assertIs(state['g']['Accessory']['value'],False)

    def test_unselected_packets_are_discarded_before_decode_and_duplicate_values_do_not_wake(self):
        address='/avatar/parameters/Accessory'
        ignored=b.osc_packet('/avatar/parameters/FT/v2/EyeLeftX','Float',.5)
        selected=b.osc_packet(address,'Bool',True)
        packets=[ignored]*1000+[selected]*100
        class Socket:
            def recvfrom(self,_):
                if packets:return packets.pop(0),('127.0.0.1',12345)
                raise OSError('done')
        transport=b.Transport.__new__(b.Transport)
        transport.activity=Mock();transport.closed=threading.Event();transport.sock=Socket();transport.notices=queue.Queue()
        transport.update_lock=threading.Lock();transport.last_received_values={};transport.parameter_updates={}
        transport.listen_addresses=frozenset({address});transport.received_packets=0
        with patch('avatar_sync.osc_updates',wraps=b.osc_updates) as decode:transport._receive()
        self.assertEqual(decode.call_count,100)
        transport.activity.set.assert_called_once()
        self.assertEqual(transport.received_packets,1100)
        self.assertEqual(transport.take_updates(),{address:('Bool',True)})


if __name__=='__main__':unittest.main()
