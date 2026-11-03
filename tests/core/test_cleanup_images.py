"""삭제 전에 모든 latest를 검증하고 페이지 전체를 정리하는지 확인한다."""

from unittest.mock import Mock

import pytest

from deploy import cleanup_images


def version(number, digest='old', tags=()):
    return {'id': number, 'name': digest, 'metadata': {'container': {'tags': list(tags)}}}


def manifest():
    return {'published': {role: {'digest': 'current'} for role in cleanup_images.ROLES}}


@pytest.mark.parametrize('owner_type,scope', [('User', 'users'), ('Organization', 'orgs')])
def test_keeps_latest_and_deletes_tagged_and_untagged_versions(monkeypatch, owner_type, scope):
    api = Mock(return_value=[version(1, 'current', ['latest', 'release']), version(2, tags=['old-release']), version(3)])
    monkeypatch.setattr(cleanup_images, 'api', api)
    cleanup_images.cleanup('Owner/MAGI', owner_type, manifest())
    deletes = [call for call in api.call_args_list if call.kwargs.get('method') == 'DELETE']
    assert len(deletes) == 6
    assert all(call.args[0].startswith(f'/{scope}/owner/packages/container/magi-') for call in deletes)
    assert all(call.args[0].endswith(('/2', '/3')) for call in deletes)


def test_mismatched_latest_prevents_all_deletes(monkeypatch):
    api = Mock(side_effect=[[version(1, 'current', ['latest'])], [version(2, 'wrong', ['latest'])]])
    monkeypatch.setattr(cleanup_images, 'api', api)
    with pytest.raises(ValueError, match='일치하지'):
        cleanup_images.cleanup('owner/magi', 'User', manifest())
    assert all(not call.kwargs for call in api.call_args_list)


def test_missing_latest_prevents_deletes(monkeypatch):
    api = Mock(return_value=[version(1)])
    monkeypatch.setattr(cleanup_images, 'api', api)
    with pytest.raises(ValueError, match='일치하지'):
        cleanup_images.cleanup('owner/magi', 'User', manifest())
    assert api.call_count == 1


def test_reads_all_pages_before_deleting(monkeypatch):
    first = [version(1, 'current', ['latest'])] + [version(i) for i in range(2, 101)]
    api = Mock(side_effect=[first, [version(101)], [version(1, 'current', ['latest'])], [version(1, 'current', ['latest'])]] + [None] * 100)
    monkeypatch.setattr(cleanup_images, 'api', api)
    cleanup_images.cleanup('owner/magi', 'User', manifest())
    assert api.call_args_list[1].args[0].endswith('page=2')
    assert len([call for call in api.call_args_list if call.kwargs.get('method') == 'DELETE']) == 100
