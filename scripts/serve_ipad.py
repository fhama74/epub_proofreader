"""One application process, bound to localhost and one private LAN address."""
import argparse,ipaddress,os,socket,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=[ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','100.64.0.0/10')]
def allowed(value):
    try:address=ipaddress.ip_address(value)
    except ValueError:return False
    return address.version==4 and any(address in network for network in PRIVATE)
def detect():
    if sys.platform=='darwin':
        for interface in ('en0','en1','en2'):
            result=subprocess.run(['ipconfig','getifaddr',interface],capture_output=True,text=True)
            if allowed(result.stdout.strip()):return result.stdout.strip()
    try:
        for address in socket.gethostbyname_ex(socket.gethostname())[2]:
            if allowed(address):return address
    except OSError:pass
    return None

def main():
    parser=argparse.ArgumentParser(description='iPad接続用サーバー（同じWi-FiまたはTailscale）')
    parser.add_argument('--host',help='MacのプライベートIPv4アドレス。省略時は自動検出')
    parser.add_argument('--port',type=int,default=8000)
    args=parser.parse_args();host=args.host or detect()
    if not host or not allowed(host):parser.error('接続先を検出できません。--host にMacのプライベートIPv4アドレスを指定してください。')
    if not 1<=args.port<=65535:parser.error('ポート番号が不正です。')
    os.chdir(ROOT);sys.path.insert(0,str(ROOT/'backend'))
    jar=ROOT/'.tools/epubcheck-5.4.0/epubcheck.jar'
    if jar.exists():os.environ.setdefault('EPUBCHECK_JAR',str(jar))
    import uvicorn
    listeners=[]
    try:
        for address in ('127.0.0.1',host):
            server=socket.socket(socket.AF_INET,socket.SOCK_STREAM);listeners.append(server)
            server.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            server.bind((address,args.port));server.listen(128);server.setblocking(False)
        print(f'\niPadのSafariで開く: http://{host}:{args.port}/\nMacで開く: http://127.0.0.1:{args.port}/\n終了: Ctrl+C\n',flush=True)
        uvicorn.Server(uvicorn.Config('epub_proofreader.app:app',host=host,port=args.port,workers=1,timeout_graceful_shutdown=5)).run(sockets=listeners)
    except OSError as exc:
        raise SystemExit(f'起動できません: {exc}\n既存のサーバーが起動中の場合は先に終了してください。')
    finally:
        for server in listeners:server.close()

if __name__=='__main__':main()
