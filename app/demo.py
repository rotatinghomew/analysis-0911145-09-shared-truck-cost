import json
import threading

from app.client import request, analysis
from app.server import make_server
from app.store import load_case


def show(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


def main():
    with make_server() as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        print(json.dumps(request(base, '/health'), ensure_ascii=False))
        cases = request(base, '/cases')['cases']
        for case in cases:
            print('\n=== legacy preview still served for case: ' + case + ' ===')
            show(request(base, '/preview', {'case': case}))
        for case in cases:
            print('\n=== cost-sharing analysis for case: ' + case + ' (baseline) ===')
            show(analysis(base, case))
            # Re-run each declared scenario through the same route so demand and
            # fleet changes are compared on exactly the same methodological base.
            from app.store import load_case
            for entry in load_case(case).get('scenarios', []):
                print('\n=== analysis for case: ' + case
                      + ' under scenario: ' + entry['name'] + ' ===')
                show(analysis(base, case, scenario=entry['name']))
        server.shutdown()
        worker.join(timeout=3)


if __name__ == '__main__':
    main()
