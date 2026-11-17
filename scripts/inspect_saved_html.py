"""Read existing stored-report inventory without initializing Workspace or calling AI."""
import argparse,json,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from urs.saved_reports import inspect_document

def main():
    p=argparse.ArgumentParser(description='저장된 HTML/실패 기록 읽기 전용 점검 (API 호출 없음)')
    p.add_argument('--data',type=Path,default=Path(__file__).resolve().parents[1]/'.runtime/workspace.sqlite')
    p.add_argument('--document');args=p.parse_args()
    try:
        with sqlite3.connect(args.data.resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON')
            jobs=db.execute('SELECT id,revision FROM jobs'+(' WHERE id=?' if args.document else ''),(args.document,) if args.document else ()).fetchall()
            reports=[]
            for job in jobs:
                info=inspect_document(db,job['id'],job['revision'])
                for r in info['available']:
                    r['metadata']={k:r['metadata'][k] for k in ('model','reasoning_effort','max_output_tokens','settings_version') if k in r['metadata']}
                reports.append({'document_id':job['id'],**info})
            print(json.dumps({'read_only':True,'api_calls':0,'reports':reports},ensure_ascii=False,indent=2))
        return 0
    except (sqlite3.Error,OSError):
        print('기존 DB를 읽지 못했습니다. DB 경로와 실행 환경을 확인하세요.',file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
