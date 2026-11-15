import asyncio
import sys
from unittest.mock import AsyncMock, Mock

import pytest

from backend.access.context import ACTOR, AccessError
from backend.access.store import AccessStore
from backend.access.service import PublicService
from backend.access.ownership import can_access, owner_ids
from backend.mcp_client.service import MCPService


def test_guest_link_preserves_data_and_revokes_old_session(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            now = [1800000000]
            access = AccessStore(store, clock=lambda: now[0])
            original = await access.login('account', 'fake-pepper')
            guest_sid = await access.guest()
            guest = await access.session(guest_sid)
            other = await access.session(await access.guest())
            async with store.transaction() as conn:
                for actor in (guest, other):
                    await conn.execute('INSERT INTO projects(id,name,owner_id) VALUES (%s,%s,%s)',
                                       (actor['id'], actor['id'], actor['id']))
            linked_sid = await access.login('account', 'fake-pepper', previous=guest_sid)
            linked = await access.session(linked_sid)
            assert linked['id'] == (await access.session(original))['id']
            assert guest['id'] in linked['owner_ids']
            with pytest.raises(AccessError):
                await access.session(guest_sid)
            context = ACTOR.set(linked)
            try:
                async with store.transaction(mode='read') as conn:
                    visible = await (await conn.execute('SELECT owner_id FROM projects')).fetchall()
                assert [row['owner_id'] for row in visible] == [guest['id']]
            finally:
                ACTOR.reset(context)
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())


def test_guest_expiry_new_google_promotion_and_oauth_binding(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            now = [1800000000]
            access = AccessStore(store, clock=lambda: now[0])
            first = await access.guest()
            first_actor = await access.session(first)
            assert first_actor['identity_kind'] == 'guest'
            now[0] += 86400
            assert await access.guest(first) == first
            assert (await access.session(first))['expires_at'] == now[0] + 30 * 86400
            second = await access.guest()
            state, browser, _, _ = await access.begin_login(first)
            with pytest.raises(AccessError):
                await access.consume_login(state, browser, second)
            linked = await access.session(await access.login('new', 'fake-pepper', previous=first))
            assert linked['id'] == first_actor['id']
            assert linked['identity_kind'] == 'google'
            with pytest.raises(AccessError):
                await access.session(first)
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())


def test_owner_scope_and_linked_usage(async_store_factory):
    assert owner_ids({'id': 'root', 'owner_ids': ['root', 'guest']}) == ('root', 'guest')
    assert can_access({'id': 'root', 'owner_ids': ['root', 'guest']}, 'guest')
    assert not can_access({'id': 'guest', 'owner_ids': ['guest']}, 'root')
    async def scenario():
        async with async_store_factory() as store:
            access = AccessStore(store, clock=lambda: 1800000000)
            root = await access.session(await access.login('account', 'fake-pepper'))
            guest_sid = await access.guest()
            guest = await access.session(guest_sid)
            async with store.transaction() as conn:
                await access.acquire(conn, guest['id'], 'guest-job', execution_id='guest-run', count=True, queued=False)
                await access.acquire(conn, root['id'], 'root-job', execution_id='root-run', count=True, queued=False)
            linked_sid = await access.login('account', 'fake-pepper', previous=guest_sid)
            linked = await access.session(linked_sid)
            assert (await access.usage(linked['id'], linked['owner_ids']))['runs'] == 2
            assert (await access.status(linked['id'], linked['owner_ids']))['own_active_count'] == 2
            manager = Mock()
            manager.knowledge.store = store
            manager.get = AsyncMock(return_value={'id': 'a' * 32, 'owner_id': guest['id']})
            service = PublicService(manager, google=None, pepper='fake-pepper', clock=lambda: 1800000000)
            auth = await service.invoke({'method': 'progress.authorize', 'params': {'id': 'a' * 32}, 'session': linked_sid}, None)
            assert guest['id'] in auth['owner_ids']
            assert auth['owner_id'] == guest['id']
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())


def test_linked_guest_mcp_snapshot_uses_original_physical_owner(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            access = AccessStore(store, clock=lambda: 1800000000)
            root = await access.session(await access.login('account', 'fake-pepper'))
            guest_sid = await access.guest()
            guest = await access.session(guest_sid)
            service = MCPService(store)
            token = ACTOR.set(guest)
            try:
                connection = await service.create(guest['id'], {'name': 'Docs', 'url': 'https://example.test/mcp', 'auth_type': 'none'})
            finally:
                ACTOR.reset(token)
            tool = {'name': 'find', 'schema_hash': 'v1', 'enabled': True, 'available': True}
            async with store.transaction() as conn:
                await conn.execute("UPDATE mcp_connections SET enabled=true,status='ready',tools=%s WHERE id=%s",
                                   (store._json([tool]), connection['id']))
            linked = await access.session(await access.login('account', 'fake-pepper', previous=guest_sid))
            token = ACTOR.set(linked)
            try:
                assert [item['id'] for item in (await service.list(root['id'], linked['owner_ids']))['connections']] == [connection['id']]
                snapshot = await service.snapshot(linked['owner_ids'])
            finally:
                ACTOR.reset(token)
            worker = await access.session_for_worker(root['id'])
            token = ACTOR.set(worker)
            try:
                available = await service.available(root['id'], snapshot)
                assert len(available) == 1 and available[0][0]['owner_id'] == guest['id']
            finally:
                ACTOR.reset(token)
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())


def test_google_link_during_running_guest_execution_keeps_original_lease(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            access = AccessStore(store, clock=lambda: 1800000000)
            await access.login('account', 'fake-pepper')
            guest_sid = await access.guest()
            guest = await access.session(guest_sid)
            async with store.transaction() as conn:
                generation = await access.acquire(conn, guest['id'], 'job', execution_id='run', queued=False, count=True)
            linked_sid = await access.login('account', 'fake-pepper', previous=guest_sid)
            linked = await access.session(linked_sid)
            async with store.transaction() as conn:
                lease = await access.execution(conn, guest['id'], 'job', generation, 'run')
            assert lease['owner_id'] == guest['id'] and lease['phase'] == 'running'
            assert (await access.status(linked['id'], linked['owner_ids']))['own_active_count'] == 1
            worker = await access.session_for_worker(guest['id'])
            assert worker['id'] == guest['id']
            assert linked['id'] in worker['owner_ids']
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())


def test_dual_session_selection_suspension_and_logout(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            access = AccessStore(store, clock=lambda: 1800000000)
            canonical = await access.login('account', 'fake-pepper')
            guest_sid = await access.guest()
            account = await access.session(canonical)
            guest = await access.session(guest_sid)
            manager = Mock()
            manager.knowledge.store = store
            service = PublicService(manager, google=None, pepper='fake-pepper', clock=lambda: 1800000000)
            async def me(primary, alternate):
                return await service.invoke({'method': 'auth.me', 'params': {}, 'session': primary,
                                             'guest_session': alternate}, None)
            assert (await me(canonical, guest_sid))['id'] == account['id']
            assert (await me('expired-session-value-000', guest_sid))['id'] == guest['id']
            async with store.transaction() as conn:
                await conn.execute('UPDATE users SET suspended=true WHERE id=%s', (account['id'],))
            with pytest.raises(AccessError):
                await me(canonical, guest_sid)
            async with store.transaction() as conn:
                await conn.execute('UPDATE users SET suspended=false WHERE id=%s', (account['id'],))
            service.release = AsyncMock()
            await service.invoke({'method': 'auth.logout', 'params': {}, 'session': canonical,
                                  'guest_session': guest_sid, 'csrf': account['csrf']}, None)
            with pytest.raises(AccessError): await access.session(canonical)
            with pytest.raises(AccessError): await access.session(guest_sid)
    if sys.platform == 'win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())


def test_oauth_state_binds_to_effective_guest_when_primary_expired(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            guest_sid = await AccessStore(store).guest()
            google = Mock(available=True)
            google.authorize.return_value = 'https://example.test/oauth'
            google.subject.return_value = 'google-subject'
            manager = Mock()
            manager.knowledge.store = store
            service = PublicService(manager, google=google, pepper='fake-pepper')
            request = {'params': {}, 'session': 'expired-session-value-000', 'guest_session': guest_sid}
            started = await service.invoke({**request, 'method': 'auth.start'}, None)
            state = google.authorize.call_args.args[0]
            linked = await service.invoke({**request, 'method': 'auth.callback',
                                           'params': {'state': state, 'browser': started['browser'], 'code': 'fake'}}, None)
            actor = await service.access.session(linked['session'])
            assert actor['identity_kind'] == 'google'
            with pytest.raises(AccessError): await service.access.session(guest_sid)
    if sys.platform == 'win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())


def test_google_session_bootstrap_does_not_overwrite_distinct_guest_cookie(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            access = AccessStore(store)
            google = await access.login('google', 'fake-pepper')
            guest = await access.guest()
            manager = Mock()
            manager.knowledge.store = store
            service = PublicService(manager, google=None, pepper='fake-pepper')
            result = await service.invoke({'method': 'auth.guest', 'params': {},
                                           'session': google, 'guest_session': guest}, None)
            assert result.get('set_guest_cookie') is False
    if sys.platform == 'win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())


def test_guest_bootstrap_does_not_bypass_suspended_alternate(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            access = AccessStore(store)
            guest_sid = await access.guest()
            actor = await access.session(guest_sid)
            async with store.transaction() as conn:
                await conn.execute('UPDATE users SET suspended=true WHERE id=%s', (actor['id'],))
            manager = Mock()
            manager.knowledge.store = store
            service = PublicService(manager, google=None, pepper='fake-pepper')
            with pytest.raises(AccessError):
                await service.invoke({'method': 'auth.guest', 'params': {},
                                      'session': 'expired-session-value-000', 'guest_session': guest_sid}, None)
    if sys.platform == 'win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())


def test_expired_cookie_allows_oauth_start_but_revoked_pending_session_stays_bound(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            access = AccessStore(store)
            expired = await access.guest()
            await access.logout(expired)
            google = Mock(available=True)
            google.authorize.return_value = 'https://example.test/oauth'
            google.subject.return_value = 'google-subject'
            manager = Mock()
            manager.knowledge.store = store
            service = PublicService(manager, google=google, pepper='fake-pepper')
            for cookies in ({'guest_session': expired}, {'session': expired}):
                start = await service.invoke({'method': 'auth.start', 'params': {}, **cookies}, None)
                state = google.authorize.call_args.args[0]
                result = await service.invoke({'method': 'auth.callback', **cookies,
                                               'params': {'state': state, 'browser': start['browser'], 'code': 'fake'}}, None)
                assert (await access.session(result['session']))['identity_kind'] == 'google'
            guest = await access.guest()
            start = await service.invoke({'method': 'auth.start', 'params': {}, 'guest_session': guest}, None)
            state = google.authorize.call_args.args[0]
            await access.logout(guest)
            with pytest.raises(AccessError):
                await service.invoke({'method': 'auth.callback', 'guest_session': guest,
                                      'params': {'state': state, 'browser': start['browser'], 'code': 'fake'}}, None)
    if sys.platform == 'win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())


def test_suspended_session_cannot_be_ignored_for_oauth_start(async_store_factory):
    async def scenario():
        async with async_store_factory() as store:
            access = AccessStore(store)
            guest = await access.guest()
            actor = await access.session(guest)
            async with store.transaction() as conn:
                await conn.execute('UPDATE users SET suspended=true WHERE id=%s', (actor['id'],))
            manager = Mock()
            manager.knowledge.store = store
            service = PublicService(manager, google=Mock(available=True), pepper='fake-pepper')
            for cookies in ({'session': guest}, {'guest_session': guest},
                            {'session': 'expired-session-value-000', 'guest_session': guest}):
                with pytest.raises(AccessError):
                    await service.invoke({'method': 'auth.start', 'params': {}, **cookies}, None)
    if sys.platform == 'win32': asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(scenario())
