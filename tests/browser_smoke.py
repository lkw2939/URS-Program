"""Real Chromium employee flow, isolated from customer data."""
import io
import secrets
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from pypdf import PdfWriter
from urs.web import make_app
from urs.workspace import Workspace


def main():
    with tempfile.TemporaryDirectory() as folder:
        workspace = Workspace(Path(folder) / 'test.sqlite')
        password = secrets.token_urlsafe(24)
        workspace.add_user('browser-test', password)
        server = make_app(workspace, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=400)
            stream = io.BytesIO()
            writer.write(stream)
            payload = stream.getvalue()
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
                page = browser.new_page(viewport={'width': 1360, 'height': 960})
                errors = []
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(f'http://127.0.0.1:{server.server_port}')
                page.get_by_label('직원 ID').fill('browser-test')
                page.get_by_label('비밀번호', exact=True).fill(password)
                page.get_by_role('button', name='로그인', exact=True).click()
                page.get_by_role('heading', name='검토할 URS를 등록하세요').wait_for()
                title = '브라우저 시험 <b>고객 요구사항</b>'
                page.get_by_label('새 프로젝트 이름').fill(title)
                page.get_by_role('button', name='프로젝트 만들기').click()
                page.get_by_role('heading', name=title, exact=True).wait_for()
                assert page.locator('#project-title b').count() == 0
                page.get_by_label('고객 원본 PDF', exact=True).set_input_files({'name':'browser-sample.pdf','mimeType':'application/pdf','buffer':payload})
                page.get_by_role('button', name='원본 등록', exact=True).click()
                page.get_by_role('heading', name='browser-sample.pdf', exact=True).wait_for()
                page.get_by_text('원본 보관 · PASS', exact=True).wait_for()
                with page.expect_download() as download_info:
                    page.get_by_role('link', name='원본 다운로드').click()
                assert Path(download_info.value.path()).read_bytes() == payload
                page.reload()
                page.get_by_role('button', name=title, exact=True).click()
                page.get_by_role('heading', name='browser-sample.pdf', exact=True).wait_for()
                evidence = Path(__file__).resolve().parents[1] / 'docs/evidence'
                evidence.mkdir(exist_ok=True)
                page.screenshot(path=str(evidence / 'stage2-desktop.png'), full_page=True)
                page.set_viewport_size({'width':390,'height':844})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(evidence / 'stage2-mobile.png'), full_page=True)
                page.get_by_role('button', name='로그아웃', exact=True).click()
                page.get_by_role('button', name='로그인', exact=True).wait_for()
                response = page.request.get(f'http://127.0.0.1:{server.server_port}/api/projects')
                assert response.status == 401
                assert not errors, errors
                browser.close()
                print('PASS: Chromium login, project, text escaping, PDF upload, source status, exact download, reload, mobile layout, logout, session revocation; no page errors.')
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == '__main__':
    main()
