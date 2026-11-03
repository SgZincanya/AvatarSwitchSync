import json
import http.server
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from avatar_sync import Transport, osc_string

udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp.bind(('127.0.0.1', 0))
udp.settimeout(2)
class FakeVRChat(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        change = {'FULL_PATH':'/avatar/change','TYPE':'s','ACCESS':1,'VALUE':['avtr_simulated']}
        if 'HOST_INFO' in self.path:
            data = {'NAME':'VRChat-Client-Test','OSC_PORT':udp.getsockname()[1]}
        elif self.path == '/avatar/change': data = change
        else: data = {'FULL_PATH':'/avatar','CONTENTS':{'change':change}}
        raw=json.dumps(data).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),FakeVRChat)
threading.Thread(target=server.serve_forever,daemon=True).start()
a=b=None
try:
    a=Transport(print)
    b=Transport(print)
    assert a.udp_port != b.udp_port
    assert a.udp_port not in (9000,9001) and b.udp_port not in (9000,9001)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{a.http.server_port}/?HOST_INFO') as response:
        assert json.load(response)['OSC_PORT'] == a.udp_port
    with opener.open(f'http://127.0.0.1:{a.http.server_port}/avatar') as response:
        assert 'change' in json.load(response)['CONTENTS']
    # Exercise discovery -> HOST_INFO -> live avatar tree without touching real VRChat.
    a.services={'VRChat-Test':server.server_port}
    result=a.snapshot()
    assert result[0]=='avtr_simulated', result
    from avatar_sync import osc_packet
    notification='/avatar/parameters/TestStaticControl'
    a.listen_addresses=frozenset({notification})
    udp.sendto(osc_packet(notification,'Int',7),('127.0.0.1',a.udp_port))
    updates={}
    for _ in range(20):
        updates.update(a.take_updates())
        if notification in updates:break
        time.sleep(.05)
    assert updates[notification]==('Int',7),updates
    udp.sendto(osc_string('/avatar/change')+osc_string(',s')+osc_string('avtr_second'),('127.0.0.1',a.udp_port))
    notices=[]
    for _ in range(10):
        notices.extend(a.changes())
        if 'avtr_second' in notices: break
        time.sleep(.1)
    assert 'avtr_second' in notices, notices
    a.last_definitions={'头发':{'name':'头发','input':{'address':'/avatar/parameters/\\u5934\\u53d1'}}}
    a.send('头发','Int',3)
    raw,_=udp.recvfrom(65535)
    assert b'\\u5934\\u53d1' in raw and raw[-4:]==b'\0\0\0\3'
    # An eye parameter remains blocked even if manually inserted into the mapping.
    a.last_definitions['FT/v2/EyeLeftX']={'name':'FT/v2/EyeLeftX','input':{'address':'/avatar/parameters/FT/v2/EyeLeftX'}}
    a.send('FT/v2/EyeLeftX','Float',.2)
    udp.settimeout(.1)
    try:
        udp.recvfrom(65535)
        raise AssertionError('Eye tracking parameter was sent')
    except socket.timeout: pass
    print('PASS: two parallel receivers, OSCQuery discovery/HTTP, avatar notification, escaped UDP write, eye protection')
finally:
    if a: a.close()
    if b: b.close()
    server.shutdown();server.server_close();udp.close()
