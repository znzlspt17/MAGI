"""공개 RPC 입구. 로컬 엔진과 분리된 사용자·독점 정책을 적용한다."""

from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import hmac
import json
import re
from uuid import uuid4

from backend.access.context import ACTOR, DEFERRED, METER, AccessError
from backend.access.billing import Meter
from backend.access.store import AccessStore, digest, day_at
from backend.access.recovery import Execution, Failure, WorkerRecovery
from backend.model_policy import default_prices


WAITING = {'NEEDS_USER_INPUT', 'PASS_PENDING_USER_APPROVAL'}
SAFE_DOC = re.compile(r'(?:final/FINAL_AGENT_SPEC\.md|draft/approval_candidate_spec\.en\.md|critical/CRITICAL_REPORT\.ko\.md|history/[0-9a-f]{32}\.md)\Z')
PUBLIC_FIELDS=set('''id request status message action created_at updated_at queued_at progress execution_id project_id retry_status retry_action can_continue read_only latest_completed source_hash step_id continuation_error state blocking_questions awaiting_input_reason review_questions question_forms saved_answers candidate final critical execution_graph version nodes legacy session_events completed_documents title input feedback answers started_at completed_at questions summary document_step_id stage duration_ms issue_counts has_document has_issues detail_available result issues resolved_issues requirements document content filename kind language recording_incomplete source target edges mode embedding_status has_more offset next_offset body attrs active logical_key sequence actor section requirement_id scope title_path question text rationale conditions sources requirement_ids decision_ids question_id question_text answer selection selected_option_ids custom_text form_version input_type options label value decision_key required_change decision_question resolution_reason missing_information severity code explanation description confirmed_basis basis_refs status_label pending total limit truncated groups node_id node_count edge_count connected_id references source_text translated_text delta number_mismatches current_status pending_questions input_type is_required allow_custom selected label_ko default_id recommended help hint requirement text_ko text_en name reason duration elapsed_ms percent total_steps completed_steps count accepted superseded implementation changes source_id requirement source_refs coverage effect expected actual resolution issue_id summary_ko request_type non_scope mandatory_requirements constraints assumptions decisions workflow_status user_reply decision_text index information priority blocking major minor passed failed resolved unresolved answer_forms custom_label instruction prompt choices option_id decision support status_text done next_action can_retry user_action required provenance change original_quote known active_session sessions'''.split())
PUBLIC_FIELDS.update('research search_method mode performed outcome result_count query retrieved_at url job_id resolution_reasons recommended_requirements optional_requirements locked_constraints document_has_more document_next_offset other_body other_kind original_text parent_id related_node_ids'.split())
PUBLIC_FIELDS.update('change_review before_id after_id before_hash after_hash before after item_id start end line meaning relation evidence analysed remaining calls diff'.split())


def user_payload(value):
    """명시적으로 승인된 사용자 결과만 전달한다."""
    if isinstance(value, list):
        return [user_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    private = {'provider','demo','usage','heartbeat','error_code','error_stage','queue_position',
               'order','queue_order','owner_id','lease_generation','ref','artifact_path','artifact_hash',
               'recording_incomplete','cache_diagnostics','model','diagnostics','workflow_constraints'}
    result={}
    for key,item in value.items():
        if key not in PUBLIC_FIELDS or key in private:
            continue
        if key=='question_forms' and isinstance(item,dict):
            result[key]={ident:user_payload(form) for ident,form in item.items()
                         if isinstance(form,dict) and ident==form.get('question_id')}
        else:
            result[key]=user_payload(item)
    if isinstance(value.get('attrs'),dict) and SAFE_DOC.fullmatch(str(value['attrs'].get('artifact_path',''))):
        result['attrs'].update({key:value['attrs'][key] for key in ('artifact_path','artifact_hash') if key in value['attrs']})
    return result


class PublicService:
    def __init__(self, manager, prices=None, google=None, pepper='', clock=None):
        if manager.knowledge is None:
            raise RuntimeError('공개 모드에는 PostgreSQL 저장소가 필요합니다.')
        self.manager, self.store = manager, manager.knowledge.store
        self.access = AccessStore(self.store, **({'clock':clock} if clock else {}))
        self.prices, self.google, self.pepper = default_prices() if prices is None else prices, google, pepper
        manager.knowledge.public_mode=True
        manager.public_service = self
        self.recovery = WorkerRecovery(self)

    def require_admin(self, actor):
        if actor['role'] != 'admin':
            raise AccessError('관리자 권한이 필요합니다.')

    def invoke(self, request, dispatch):
        method, params = request['method'], dict(request['params'])
        sid = request.get('session')
        if method == 'auth.info':
            return {'public':True, 'login_available':bool(self.google and self.google.available and self.pepper)}
        if method in {'auth.start','auth.callback'} and not self.pepper:
            raise AccessError('백엔드에 SUBJECT_PEPPER 설정이 필요합니다.', 'unavailable')
        if method == 'auth.start':
            if not self.google or not self.google.available:
                raise AccessError('Google OAuth 클라이언트 설정을 확인하세요.', 'unavailable')
            state, browser, nonce, verifier = self.access.begin_login()
            return {'url': self.google.authorize(state, nonce, verifier), 'browser':browser}
        if method == 'auth.callback':
            if not self.google or not self.google.available:
                raise AccessError('Google OAuth 클라이언트 설정을 확인하세요.', 'unavailable')
            state = self.access.consume_login(params.get('state'), params.get('browser'))
            subject = self.google.subject(params.get('code'), state['nonce'], state['verifier'])
            return {'session': self.access.login(subject, self.pepper, sid)}
        actor = self.access.session(sid)
        self.access.throttle(actor['id'])
        if request.get('csrf') is not None and not hmac.compare_digest(str(request['csrf']), actor['csrf']):
            raise AccessError('요청 확인 값이 올바르지 않습니다.')
        mutations = {'generate','answer','revise','approve','continue','lease.keep','lease.release','lease.resume','auth.logout'}
        if (method in mutations or method.startswith(('cleanup.','admin.')) or method == 'knowledge.retry' or method == 'document') and method != 'cleanup.catalog':
            if not hmac.compare_digest(str(request.get('csrf','')), actor['csrf']):
                raise AccessError('요청 확인 값이 필요합니다.')
        if method == 'auth.me':
            return {'id':actor['id'], 'role':actor['role'], 'expires_at':actor['expires_at'], 'csrf':actor['csrf']}
        if method == 'auth.logout':
            self.release(actor['id'])
            self.access.logout(sid)
            return {'ok':True}
        if method == 'service.status':
            return self.access.status(actor['id'])
        if method == 'usage':
            return self.access.usage(actor['id'])
        if method == 'lease.release':
            self.release(actor['id'], require_owner=True)
            return self.access.status(actor['id'])
        if method == 'lease.keep':
            with self.store.transaction() as c:
                lease = self.access.lease(c)
                if lease['owner_id'] != actor['id'] or lease['phase'] != 'waiting':
                    raise AccessError('유지할 사용권이 없습니다.', 'busy')
                c.execute('UPDATE service_lease SET deadline=%s WHERE singleton=1', (self.access.clock()+180,))
            return self.access.status(actor['id'])
        if method.startswith('admin.'):
            self.require_admin(actor)
            return self.admin(actor, method, params)
        token = ACTOR.set(actor)
        try:
            if method == 'list':
                return user_payload([self.manager.summary(i) for i in self.manager.ids()])
            if method.startswith('projects.'):
                return [] if method == 'projects.list' else self._deny()
            if method.startswith('cleanup.'):
                return self.cleanup(actor, method, params)
            if method == 'knowledge.retry':
                self.require_admin(actor)
                with self.temporary(actor,'maintenance'):
                    mark=ACTOR.set(None)
                    try:
                        ok=self.manager.knowledge.reindex()
                        with self.store.transaction() as c:
                            c.execute('INSERT INTO admin_audit(id,actor_id,action) VALUES (%s,%s,%s)',(uuid4().hex,actor['id'],'knowledge.retry'))
                        return {'status':'completed' if ok else 'failed'}
                    finally:
                        ACTOR.reset(mark)
            if method == 'knowledge.document' and not SAFE_DOC.fullmatch(str(params.get('path',''))):
                raise KeyError('document')
            if method == 'knowledge.node':
                # 저장 원문 전체 대신 사용자에게 허용된 노드와 본문만 제공한다.
                result = self.manager.knowledge_call(method, params)
                if not SAFE_DOC.fullmatch(str(result.get('attrs',{}).get('artifact_path',''))):
                    result.pop('document',None)
                return user_payload(result)
            if method in {'generate','answer','revise','approve','continue','lease.resume'}:
                return self.admit(actor, request, dispatch)
            if method == 'document':
                self.manager.get(params.get('id'))
                if params.get('language')=='en':
                    return self.result(dispatch({**request,'params':params}))
                if params.get('language') == 'ko':
                    cached = self.cached_document(params)
                    if cached is not None:
                        return user_payload(cached)
            temporary = method in {'document','knowledge.search','knowledge.graph','knowledge.retry'}
            if temporary:
                with self.temporary(actor, params.get('id') or 'read-operation'):
                    return self.result(dispatch({**request,'params':params}))
            if method not in {'get','download','knowledge.document','subscribe'}:
                raise AccessError('요청을 처리할 수 없습니다.', 'invalid')
            return self.result(dispatch({**request,'params':params}))
        finally:
            ACTOR.reset(token)

    @staticmethod
    def _deny():
        raise AccessError('지원하지 않는 요청입니다.', 'invalid')

    @staticmethod
    def result(raw):
        response = json.loads(raw)
        if 'error' in response:
            raise AccessError(response['error']['message'],response['error']['code'])
        return user_payload(response.get('result'))

    def release(self, uid, *, require_owner=False):
        with self.store.transaction() as c:
            row = self.access.lease(c)
            if require_owner and row['owner_id'] != uid:
                raise AccessError('종료할 사용권이 없습니다.', 'forbidden')
            if row['owner_id'] == uid:
                if row['phase'] == 'waiting':
                    self.access.clear(c)
                else:
                    c.execute('UPDATE service_lease SET stopping=true WHERE singleton=1')

    def cached_document(self, params):
        from backend.services.spec_translation import source_key
        detail = self.manager.step(params['id'], params['step_id'])
        doc = detail.get('document')
        if not doc:
            raise KeyError('document')
        root = self.manager.artifact(params['id'], 'translations/'+source_key(doc['content']))
        if not (root/'translation.ko.json').is_file():
            return None
        # 캐시 전용 함수는 원격 호출을 하지 않는다.
        from backend.services.spec_translation import cached_translation
        return cached_translation(doc, root)

    def admit(self, actor, request, dispatch):
        key = request.get('idempotency_key')
        if not isinstance(key,str) or not 8 <= len(key) <= 128:
            raise AccessError('중복 방지 요청 키가 필요합니다.', 'invalid')
        method, params = request['method'], request['params']
        fingerprint = digest(json.dumps([method,params],sort_keys=True,ensure_ascii=False))
        deferred = []
        with self.manager.lock:
            old_jobs = deepcopy(self.manager.jobs)
            mark = DEFERRED.set(deferred)
            try:
                with self.store.transaction() as c:
                    self.access.lease(c)
                    previous = c.execute('SELECT fingerprint,result FROM admissions WHERE user_id=%s AND key=%s', (actor['id'],key)).fetchone()
                    if previous:
                        if previous['fingerprint'] != fingerprint:
                            raise AccessError('같은 요청 키에 다른 입력을 사용할 수 없습니다.', 'busy')
                        return previous['result']
                    if method != 'generate':
                        self.manager.get(params.get('id'))
                    # 검증 실패는 전체 접수 트랜잭션과 메모리 상태를 되돌린다.
                    if method == 'lease.resume':
                        job = self.manager.get(params['id'])
                        if job['status'] not in WAITING:
                            raise AccessError('현재 작업은 응답 대기 상태가 아닙니다.', 'busy')
                        self.access.acquire(c,actor['id'],job['id'])
                        c.execute("UPDATE service_lease SET phase='waiting',deadline=%s WHERE singleton=1", (self.access.clock()+180,))
                        result = self.manager.summary(job['id'])
                    else:
                        # 생성 ID는 기존 엔진에서 만든 뒤 같은 DB 트랜잭션 안에서 사용권에 연결한다.
                        jid = params.get('id') or 'pending'
                        generation = self.access.acquire(c,actor['id'],jid,count=method in {'generate','continue'})
                        meter = Meter(self.access,actor['id'],jid,generation,self.prices)
                        from backend.config import Config
                        model = Config.default().model_routing['interviewer'].model
                        if method != 'approve':
                            maximum = meter.maximum(model)
                            self.access.check_money(c,actor['id'],maximum, day_at(self.access.clock()))
                        result = self.result(dispatch(request))
                        jid = result['id']
                        c.execute('UPDATE service_lease SET job_id=%s WHERE singleton=1', (jid,))
                        job = self.manager.jobs[jid]
                        job['lease_generation'] = generation
                        self.store._save_job(c,job)
                        if method != 'approve':
                            ident = self.access.reserve(actor['id'],jid,generation,model,maximum)
                            job['_initial_reservation'] = (ident,model)
                    result = user_payload(result)
                    c.execute('INSERT INTO admissions VALUES (%s,%s,%s,%s)', (actor['id'],key,fingerprint,self.store._json(result)))
            except Exception:
                self.manager.jobs = old_jobs
                raise
            finally:
                DEFERRED.reset(mark)
            for jid, action, payload in deferred:
                try:
                    self.manager._submit_locked(jid,action,payload)
                except RuntimeError:
                    raise AccessError('작업 접수 후 실행하지 못했습니다. 기록을 확인하세요.', 'unavailable') from None
        return result

    @contextmanager
    def temporary(self, actor, jid):
        owned = False
        with self.manager.lock, self.store.transaction() as c:
            lease = self.access.lease(c)
            if jid=='maintenance' and lease['phase']!='idle':
                raise AccessError('작업 사용권이 해제된 뒤 운영 작업을 실행하세요.', 'busy')
            if lease['owner_id'] == actor['id'] and lease['phase']=='waiting':
                if jid not in {'read-operation',lease['job_id']}:
                    raise AccessError('현재 작업의 처리만 진행할 수 있습니다.', 'busy')
                generation = lease['generation']
                c.execute("UPDATE service_lease SET phase='running',deadline=NULL WHERE singleton=1")
                owned = True
            else:
                generation = self.access.acquire(c,actor['id'],jid)
        active_jid = lease['job_id'] if owned else jid
        mark = METER.set(Meter(self.access,actor['id'],active_jid,generation,self.prices))
        try:
            yield
        finally:
            METER.reset(mark)
            self.access.finish(active_jid,generation,waiting=owned)

    def worker(self, ident, action, payload, *, execution=None):
        actor_token = meter_token = None
        meter = None
        entered = False
        try:
            with self.manager.lock:
                job = self.manager.jobs[ident]
                execution = execution or Execution.from_job(job)
                if (job.get('execution_id') != execution.execution_id
                    or job.get('lease_generation') != execution.generation):
                    raise AccessError('이전 실행은 재개할 수 없습니다.', 'busy')
            actor = self.access.session_for_worker(job['owner_id'])
            actor_token = ACTOR.set(actor)
            meter = Meter(self.access, actor['id'], ident, execution.generation,
                          self.prices, execution.initial)
            meter_token = METER.set(meter)
            with self.store.transaction() as c:
                lease = self.access.lease(c)
                if lease['job_id'] != ident or lease['generation'] != execution.generation or lease['phase'] != 'running':
                    raise AccessError('이전 실행은 재개할 수 없습니다.', 'busy')
            with self.manager.lock:
                job.pop('_initial_reservation', None)
            entered = True
            self.manager._run(ident,action,payload)
            if meter.initial:
                self.access.settle(meter.initial[0], Decimal(0))
            self.access.finish(ident, execution.generation, waiting=job['status'] in WAITING)
        except Exception:
            if execution is not None:
                self.recovery.record(Failure(execution, entered,
                                             meter.initial if meter is not None else execution.initial))
            raise
        finally:
            if meter_token is not None:
                METER.reset(meter_token)
            if actor_token is not None:
                ACTOR.reset(actor_token)

    def cleanup(self, actor, method, params):
        self.require_admin(actor)
        if method=='cleanup.catalog':
            token=ACTOR.set(None)
            try:
                return self.manager.cleanup.catalog()
            finally:
                ACTOR.reset(token)
        if method=='cleanup.execute':
            op=self.manager.cleanup.load(params.get('id'))
            with self.store.transaction() as c:
                allowed=c.execute("SELECT 1 FROM admin_audit WHERE actor_id=%s AND action='cleanup.preview' AND target_id=%s",(actor['id'],op['id'])).fetchone()
            if not allowed:
                raise AccessError('본인이 확인한 삭제 요청만 실행할 수 있습니다.')
        elif method!='cleanup.preview':
            self._deny()
        with self.temporary(actor,'maintenance'):
            token=ACTOR.set(None)
            try:
                owners={jid:self.manager.jobs.get(jid,{}).get('owner_id') for jid in
                        (self.manager.cleanup.load(params['id'])['targets'] if method=='cleanup.execute' else [])}
                # 정리 서비스의 DB 커밋 후 파일 삭제 순서를 외부 트랜잭션으로 감싸지 않는다.
                result=getattr(self.manager.cleanup,method.split('.')[1])(params)
                if method=='cleanup.execute' and self.manager.on_change:
                    for owner in set(owners.values())-{None}:
                        self.manager.on_change({'event':'records.deleted','ids':[jid for jid,uid in owners.items() if uid==owner],
                                                '_owner_id':owner})
                with self.store.transaction() as c:
                    c.execute('INSERT INTO admin_audit(id,actor_id,action,target_id) VALUES (%s,%s,%s,%s)',
                              (uuid4().hex,actor['id'],method,result['id']))
                return result
            finally:
                ACTOR.reset(token)

    def admin(self, actor, method, params):
        if method in {'admin.usage','admin.usage.rows'}:
            from backend.access.usage import usage
            self.require_admin(actor)
            return usage(self,method,params)
        if method in {'admin.projects','admin.jobs','admin.graph','admin.search','admin.node','admin.document'}:
            return self.admin_knowledge(actor, method, params)
        with self.manager.lock, self.store.transaction() as c:
            if method=='admin.overview':
                return {'users':c.execute('SELECT id,role,suspended,daily_runs,daily_usd FROM users ORDER BY id').fetchall(),
                        'costs':c.execute('SELECT id,day,user_id,job_id,model,reserved,actual,state FROM cost_calls ORDER BY day DESC LIMIT 200').fetchall(),
                        'lease':self.access.lease(c),'embedding_status':self.manager.knowledge.last_error,
                        'daily_usd':c.execute('SELECT daily_usd FROM service_settings WHERE singleton=1').fetchone()['daily_usd'],
                        'unowned':c.execute('SELECT id FROM jobs WHERE owner_id IS NULL ORDER BY id').fetchall()}
            if method=='admin.user_jobs':
                owner=params.get('owner_id')
                if not isinstance(owner,str) or not owner.strip():
                    raise AccessError('사용자 ID를 선택하세요.')
                if not c.execute('SELECT id FROM users WHERE id=%s',(owner,)).fetchone():
                    raise AccessError('사용자를 찾을 수 없습니다.')
                return c.execute("SELECT id,owner_id,data->>'request' AS request,data->>'status' AS status,data->>'created_at' AS created_at FROM jobs WHERE owner_id=%s ORDER BY data->>'created_at' DESC NULLS LAST,id",(owner,)).fetchall()
            if method=='admin.job':
                result=self.manager.public(params.get('id'))
                result['owner_id']=self.manager.jobs[params['id']].get('owner_id')
                c.execute('INSERT INTO admin_audit(id,actor_id,action,target_id) VALUES (%s,%s,%s,%s)',(uuid4().hex,actor['id'],method,params.get('id')))
                return result
            if method=='admin.user':
                role, runs, usd=params.get('role'),params.get('daily_runs'),Decimal(str(params.get('daily_usd')))
                if role not in {'user','admin'} or type(runs) is not int or not 0<=runs<=10000 or not usd.is_finite() or not 0<=usd<=10000 or type(params.get('suspended')) is not bool:
                    self._deny()
                # 동시 권한 변경에서도 마지막 활성 관리자를 보존한다.
                c.execute('LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE')
                target=c.execute('SELECT role,suspended FROM users WHERE id=%s',(params.get('id'),)).fetchone()
                if not target:
                    raise AccessError('사용자를 찾을 수 없습니다.')
                if target['role']=='admin' and not target['suspended'] and (role!='admin' or params['suspended']):
                    remaining=c.execute("SELECT count(*) AS total FROM users WHERE role='admin' AND NOT suspended").fetchone()['total']
                    if remaining<=1:
                        raise AccessError('마지막 활성 관리자는 권한을 내리거나 정지할 수 없습니다.')
                c.execute('UPDATE users SET role=%s,daily_runs=%s,daily_usd=%s,suspended=%s WHERE id=%s',
                          (role,runs,usd,params['suspended'],params.get('id')))
                c.execute('UPDATE sessions SET revoked=true WHERE user_id=%s',(params.get('id'),))
            elif method=='admin.claim':
                if self.access.lease(c)['phase']!='idle':
                    raise AccessError('사용 중에는 이관할 수 없습니다.', 'busy')
                jid=params.get('id')
                job=self.manager.jobs.get(jid)
                if not job or job.get('owner_id'):
                    raise KeyError(jid)
                owner=params.get('owner_id')
                if not c.execute('SELECT id FROM users WHERE id=%s',(owner,)).fetchone():
                    raise KeyError(owner)
                c.execute("UPDATE jobs SET owner_id=%s,data=jsonb_set(data,'{owner_id}',to_jsonb(%s::text)) WHERE id=%s AND owner_id IS NULL",(owner,owner,jid))
                job['owner_id']=owner
            elif method=='admin.stop':
                lease=self.access.lease(c)
                if lease['phase']=='waiting':
                    self.access.clear(c)
                else:
                    c.execute('UPDATE service_lease SET stopping=true WHERE singleton=1')
            elif method=='admin.settings':
                cap=Decimal(str(params.get('daily_usd')))
                if not cap.is_finite() or not 0<=cap<=10000:
                    self._deny()
                c.execute('UPDATE service_settings SET daily_usd=%s WHERE singleton=1',(cap,))
            elif method=='admin.settle':
                actual=Decimal(str(params.get('actual')))
                if not actual.is_finite() or actual<0:
                    self._deny()
                self.access.settle(params.get('id'),actual,source='manual')
            else:
                self._deny()
            c.execute('INSERT INTO admin_audit(id,actor_id,action,target_id) VALUES (%s,%s,%s,%s)',(uuid4().hex,actor['id'],method,params.get('id')))
            return {'ok':True}

    def admin_knowledge(self, actor, method, params):
        """전체 지식 접근은 관리자 조회 범위 안에서만 소유권 필터를 해제한다."""
        self.require_admin(actor)
        token=ACTOR.set(None)
        try:
            with self.store.transaction() as c:
                if method=='admin.projects':
                    return c.execute('SELECT id,name FROM projects ORDER BY created_at,id').fetchall()
                project=params.get('project_id')
                if not project or not c.execute('SELECT 1 FROM projects WHERE id=%s',(project,)).fetchone():
                    raise KeyError('project')
                if method=='admin.jobs':
                    return c.execute("SELECT id,data->>'request' AS request FROM jobs WHERE project_id=%s ORDER BY id",(project,)).fetchall()
                job=params.get('job_id')
                if job and not c.execute('SELECT 1 FROM jobs WHERE id=%s AND project_id=%s',(job,project)).fetchone():
                    raise KeyError('job')
                node=params.get('node_id')
                if node and not c.execute('SELECT 1 FROM nodes n JOIN jobs j ON j.id=n.job_id WHERE n.id=%s AND j.project_id=%s AND (%s::text IS NULL OR j.id=%s)',(node,project,job,job)).fetchone():
                    raise KeyError('node')
                if method=='admin.node' and not node:
                    raise KeyError('node')
                if method=='admin.document' and (not job or not SAFE_DOC.fullmatch(str(params.get('path','')))):
                    raise KeyError('document')
            result=self.manager.knowledge_call('knowledge.'+method.split('.')[1],params)
            if method=='admin.node':
                if not SAFE_DOC.fullmatch(str(result.get('attrs',{}).get('artifact_path',''))):
                    result.pop('document',None)
                # 프로젝트 밖으로 이어지는 관계는 상세 패널에서도 노출하지 않는다.
                with self.store.transaction() as c:
                    connected=list({ident for edge in result.get('edges',[]) for ident in (edge['source'],edge['target'])})
                    allowed={r['id'] for r in c.execute('SELECT n.id FROM nodes n JOIN jobs j ON j.id=n.job_id WHERE j.project_id=%s AND n.id=ANY(%s)',(project,connected)).fetchall()}
                result['edges']=[e for e in result.get('edges',[]) if e['source'] in allowed and e['target'] in allowed]
            return user_payload(result)
        finally:
            ACTOR.reset(token)
