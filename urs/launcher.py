"""Identify the exact project listener before stopping it; never kill by port alone."""
import errno
import os
from pathlib import Path
import signal
import socket
import time
import urllib.request

class StartupError(RuntimeError):
    pass

def port_busy(port):
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:sock.bind(('127.0.0.1',port));return False
        except OSError as exc:
            if exc.errno==errno.EADDRINUSE:return True
            raise

def _listening_inodes(port):
    inodes=set()
    for name in ('tcp','tcp6'):
        path=Path('/proc/net')/name
        if not path.exists():continue
        for line in path.read_text().splitlines()[1:]:
            fields=line.split();address,number=fields[1].split(':')
            accepted=address in ('0100007F','00000000') if name=='tcp' else address=='0'*32
            if accepted and int(number,16)==port and fields[3]=='0A':inodes.add(fields[9])
    return inodes

def _option(args,name,default):
    for i,arg in enumerate(args):
        if arg==name:return args[i+1] if i+1<len(args) else None
        if arg.startswith(name+'='):return arg[len(name)+1:]
    return default

def _matches(pid,root,port):
    path=Path('/proc')/str(pid)
    try:
        if path.stat().st_uid!=os.geteuid() or (path/'cwd').resolve()!=root:return False
        args=(path/'cmdline').read_bytes().decode(errors='replace').strip('\0').split('\0')
        index=args.index('-m')
        if args[index+1]!='urs' or 'serve' not in args[index+2:]:return False
        if int(_option(args,'--port','8795'))!=port:return False
        data=_option(args,'--data','.runtime/workspace.sqlite')
        if data is None or (root/data).resolve()!=(root/'.runtime/workspace.sqlite').resolve():return False
        return True
    except (OSError,ValueError,IndexError):return False

def listener_pids(port):
    inodes=_listening_inodes(port);pids=set()
    if not inodes:return pids
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():continue
        try:
            for fd in (process/'fd').iterdir():
                try:target=os.readlink(fd)
                except OSError:continue
                if target.startswith('socket:[') and target[8:-1] in inodes:
                    pids.add(int(process.name));break
        except OSError:continue
    return pids

def owned_listener_pids(root,port):
    root=Path(root).resolve()
    if not Path('/proc/net/tcp').exists():return set()
    return {pid for pid in listener_pids(port) if _matches(pid,root,port)}

def release_owned_port(root,port,timeout=10):
    root=Path(root).resolve()
    if not port_busy(port):return []
    if not Path('/proc/net/tcp').exists():raise StartupError(f'{port} 포트를 사용 중입니다. 기존 서버 터미널에서 Ctrl+C로 종료해 주세요.')
    pids=listener_pids(port)
    if not pids or any(not _matches(pid,root,port) for pid in pids):
        raise StartupError(f'{port} 포트를 다른 프로그램 또는 확인할 수 없는 프로세스가 사용 중입니다. 자동 종료하지 않았습니다.')
    stopped=[]
    for pid in pids:
        pidfd=None
        try:
            if hasattr(os,'pidfd_open') and hasattr(signal,'pidfd_send_signal'):
                pidfd=os.pidfd_open(pid)
                if not _matches(pid,root,port):raise StartupError('프로세스 식별 정보가 바뀌어 종료하지 않았습니다.')
                signal.pidfd_send_signal(pidfd,signal.SIGTERM)
            else:
                if not _matches(pid,root,port):raise StartupError('프로세스 식별 정보가 바뀌어 종료하지 않았습니다.')
                os.kill(pid,signal.SIGTERM)
            stopped.append(pid)
        except ProcessLookupError:pass
        except PermissionError:raise StartupError('같은 URS 서버를 확인했지만 종료 권한이 없습니다. 기존 서버 터미널에서 Ctrl+C로 종료해 주세요.') from None
        finally:
            if pidfd is not None:os.close(pidfd)
    deadline=time.monotonic()+timeout
    while port_busy(port) and time.monotonic()<deadline:time.sleep(.1)
    if port_busy(port):raise StartupError('기존 URS 서버 종료를 기다리고 있습니다. 새 서버는 중복 실행하지 않았습니다.')
    return stopped

def wait_ready(child,port,timeout=15):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if child.poll() is not None:raise StartupError(f'서버 프로세스가 종료됐습니다(종료 코드 {child.returncode}). 위 오류를 확인하세요.')
        try:
            with opener.open(f'http://127.0.0.1:{port}/',timeout=.5) as response:
                if response.status==200 and b'URS AI REPORT SYSTEM' in response.read(32768):return
        except OSError:pass
        time.sleep(.1)
    raise StartupError('로컬 HTTP 응답을 확인하지 못했습니다. 실행 성공으로 표시하지 않았습니다.')
