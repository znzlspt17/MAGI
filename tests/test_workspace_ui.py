"""외부 모델 호출 없이 문서 탐색·삭제 확인을 브라우저에서 검증한다."""

from pathlib import Path
import shutil
import subprocess
import threading
import time

import pytest
from werkzeug.serving import make_server
from gateway.app import create_app


class WorkspaceClient:
    jobs = []
    projects = [{'id': 'b' * 32, 'name': '튜토리얼 게임'}]

    def __init__(self, url):
        pass

    def events(self):
        yield {'event': 'ready'}
        while True:
            time.sleep(.5)
            yield {'event': 'job.changed'}

    @classmethod
    def reset(cls):
        cls.jobs = [{'id': 'a' * 32, 'request': '튜토리얼 스테이지의 이동과 전투 명세',
                     'project_id': 'b' * 32, 'status': 'FINALIZED', 'created_at': '2026-10-17T09:00:00Z',
                     'message': '최종 명세가 준비되었습니다.',
                     'can_continue': True, 'execution_id': 'e' * 32, 'latest_completed': {'step_id': 'final'},
                     'session_events': [{'id': 'e' * 32, 'action': 'generate', 'input': {'request': '튜토리얼 스테이지의 이동과 전투 명세'}, 'status': 'FINALIZED', 'started_at': '2026-10-17T09:00:00Z'}],
                     'execution_graph': {'nodes': [{'id': 'final', 'stage': 'approve', 'title': '승인 완료',
                         'status': 'completed', 'has_document': True, 'detail_available': True}]}}]

    def call(self, method, params=None):
        if method == 'list':
            return self.jobs
        if method == 'projects.list':
            return self.projects
        if method == 'get':
            if params.get('step_id'):
                return {'result': {'status': 'FINALIZED', 'questions': [{'question_id': 'REVIEW-1', 'question': '잡몹과 보스는 어떤 행동을 해야 합니까?'}], 'review_questions': [{'question_id': 'REVIEW-1', 'requirement_ids': ['REQ-005'], 'missing_information': ['잡몹과 보스의 행동 및 탄환에 대한 반응을 확인해야 합니다. ' * 10], 'resolution_reasons': ['전투 방식에 영향을 주는 선택이므로 사용자 확인이 필요합니다.']}]}, 'document': {'content': '# Tutorial Stage 1\n\n## 1. 목표\n\n키보드로 이동하고 전투하는 튜토리얼 게임을 만듭니다.\n\n## 2. 플레이어 행동\n\n- 좌우 이동과 점프\n- 보는 방향으로 대시와 발사\n\n## 3. 검증\n\n로컬 파일을 열어 스테이지를 완료할 수 있는지 확인합니다.', 'filename': 'FINAL_AGENT_SPEC.md'}}
            return self.jobs[0]
        if method == 'document':
            return {**self.call('get', {'step_id': 'final'})['document'], 'language': params['language']}
        if method == 'continue':
            assert params['id'] == self.jobs[0]['id']
            assert params['execution_id'] == self.jobs[0]['execution_id']
            self.jobs[0]['execution_id'] = 'f' * 32
            self.jobs[0]['session_events'].append({'id': 'f' * 32, 'action': 'revise',
                'input': {'feedback': params['payload']}, 'status': 'FINALIZED', 'started_at': '2026-10-17T09:30:00Z'})
            return self.jobs[0]
        if method == 'cleanup.catalog':
            return {'jobs': self.jobs, 'projects': self.projects, 'database': True, 'pending': []}
        if method == 'cleanup.preview':
            return {'id': 'c' * 32, 'scope': params['scope'], 'counts': {'jobs': 1, 'files': 4, 'bytes': 4096, 'magi_nodes': 3, 'magi_chunks': 5, 'magi_chunk_vectors': 5}, 'external_references': 1, 'skipped': []}
        if method == 'cleanup.execute':
            self.jobs.clear()
            return {'state': 'completed', 'counts': {'jobs': 1}, 'targets': ['a' * 32]}
        if method == 'knowledge.graph':
            return {'nodes': [], 'edges': [], 'has_more': False}
        raise AssertionError(method)


def fixture_app():
    WorkspaceClient.reset()
    return create_app({'MAGI_PUBLIC_MODE': False, 'TESTING': True, 'MAGI_CLIENT_FACTORY': WorkspaceClient})


def test_document_navigation_and_cleanup_confirmation():
    node = shutil.which('node')
    packages = Path(node).parent.parent / 'node_modules' if node else Path('/missing')
    if not (packages / 'playwright').is_dir():
        pytest.skip('Playwright 런타임이 없습니다.')
    server = make_server('127.0.0.1', 0, fixture_app(), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run([node, str(Path(__file__).with_name('workspace_ui.mjs')), str(packages),
                                 f'http://127.0.0.1:{server.server_port}'], capture_output=True, text=True,
                                encoding='utf-8', timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        assert result.returncode == 0, result.stderr
    finally:
        server.shutdown()
        thread.join(5)


if __name__ == '__main__':
    make_server('127.0.0.1', 5099, fixture_app(), threaded=True).serve_forever()
