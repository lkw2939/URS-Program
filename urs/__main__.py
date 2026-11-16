import argparse
import getpass
import os
import json
from pathlib import Path
from dotenv import load_dotenv

from urs.web import make_app
from urs.workspace import Workspace


def main():
    # Local operator settings; injected environment bindings keep precedence.
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False, interpolate=False)
    parser = argparse.ArgumentParser(description='URS AI REPORT SYSTEM — local development')
    parser.add_argument('--data', default='.runtime/workspace.sqlite')
    sub = parser.add_subparsers(dest='command', required=True)
    add = sub.add_parser('add-user')
    add.add_argument('username')
    reset = sub.add_parser('reset-password', help='운영자용 직원 비밀번호 복구 및 기존 세션 무효화')
    reset.add_argument('username')
    for command in ('check-terminology','import-terminology'):
        terms=sub.add_parser(command,help='검토된 용어집 검사/등록 (외부 요청 없음)')
        terms.add_argument('file')
    qualification = sub.add_parser('record-evaluation', help='전문가 대조 평가집 JSON 등록')
    qualification.add_argument('file')
    backup = sub.add_parser('backup', help='작업 DB를 새 파일로 백업')
    backup.add_argument('file')
    restore = sub.add_parser('restore', help='백업 DB를 --data의 새 경로로 복구')
    restore.add_argument('file')
    serve = sub.add_parser('serve')
    serve.add_argument('--port', type=int, default=8795)
    args = parser.parse_args()
    if args.command in ('check-terminology','import-terminology'):
        from urs.terminology import load,import_reviewed
        try:
            if args.command=='import-terminology':result=import_reviewed(args.file)
            else:
                value=load(args.file)
                if value['status']!='REVIEWED_REFERENCE':raise ValueError('용어집 파일이 없습니다.')
                result={'status':value['status'],'entries':len(value['entries']),'sha256':value['sha256']}
        except (ValueError,OSError):parser.exit(1,'용어집 검사/등록 실패: 파일·출처·검토 승인·기존 등록 파일을 확인하세요.\n')
        print(json.dumps(result,ensure_ascii=False))
        return
    if args.command in ('backup','restore'):
        from urs.backup import backup_database,restore_database
        try:
            result=backup_database(args.data,args.file) if args.command=='backup' else restore_database(args.file,args.data)
        except (ValueError,OSError) as exc:
            parser.exit(1,str(exc)+'\n')
        print(json.dumps(result,ensure_ascii=False))
        return
    Path(args.data).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    workspace = Workspace(args.data)
    os.chmod(args.data, 0o600)
    if args.command in ('add-user','reset-password'):
        password = getpass.getpass('비밀번호 (12자 이상): ')
        if password != getpass.getpass('비밀번호 확인: '):
            parser.error('비밀번호가 일치하지 않습니다.')
        try:
            if args.command=='add-user':workspace.add_user(args.username,password)
            else:workspace.reset_password(args.username,password)
        except ValueError as exc:parser.exit(1,str(exc)+'\n')
        print('직원 계정을 생성했습니다.' if args.command=='add-user' else '비밀번호를 변경하고 해당 직원의 기존 로그인 세션을 무효화했습니다.')
    elif args.command == 'record-evaluation':
        from urs.evaluation import record
        report=json.loads(Path(args.file).read_text())
        print(json.dumps(record(workspace.workflow,os.environ.get('URS_OPENAI_MODEL',''),report),ensure_ascii=False))
    else:
        server = make_app(workspace, args.port)
        print('URS 개발 서버 실행 — 로컬 포트', server.server_port, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
