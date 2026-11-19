"""Prepare the local layout browser before stopping an existing service; no API access."""
import subprocess
PROBE="""import shutil
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 exe=shutil.which('chromium') or shutil.which('chromium-browser')
 b=p.chromium.launch(**({'executable_path':exe} if exe else {}),args=['--no-sandbox','--disable-dev-shm-usage']);b.close()
"""
def ensure(root,python):
 if not (root/'requirements.lock').is_file():return True
 def execute(args,timeout):
  try:return subprocess.run([str(python),*args],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout).returncode==0
  except (OSError,subprocess.TimeoutExpired):return False
 if execute(['-c',PROBE],25):return True
 print('보고서 화면 검사에 필요한 Playwright·Chromium을 준비합니다. API는 호출하지 않습니다.',flush=True)
 if not execute(['-m','pip','install','-r','requirements.lock'],360) or not execute(['-m','playwright','install','--with-deps','chromium'],600) or not execute(['-c',PROBE],25):
  print('브라우저 준비 실패. 실행 중인 기존 서버는 종료하지 않았습니다. 서버의 패키지 설치 권한·네트워크를 확인하세요.',flush=True);return False
 print('보고서 검사 브라우저 실행 확인 완료.',flush=True);return True
