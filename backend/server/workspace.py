"""기존 작업 API를 유스케이스에 연결하는 호환 진입점."""
from _thread import LockType
from backend.application.workspace_access import WorkspaceAccess
from backend.application.job_queries import JobQueries
from backend.application.document_queries import DocumentQueries
from backend.application.requirement_queries import RequirementQueries
from backend.application.impact_queries import ImpactQueries
from backend.application.project_queries import ProjectQueries


class Workspace:
    def __init__(self, knowledge, engine_factory, lock, activities):
        self.knowledge, self.lock, self._activities = knowledge, lock, activities
        self._document_locks: dict[tuple[str, str], LockType] = {}
        self._access = WorkspaceAccess(knowledge, engine_factory)
        self._jobs = JobQueries(self._access)
        self._documents = DocumentQueries(self._access, lock=lock, activities=activities, document_locks=self._document_locks)
        self._requirements = RequirementQueries(self._access, lock=lock, documents=self._documents)
        self._impact = ImpactQueries(self._access, lock=lock, activities=activities, document_locks=self._document_locks)
        self._projects = ProjectQueries(self._access)

    @property
    def engine_factory(self):
        return self._access.engine_factory

    @engine_factory.setter
    def engine_factory(self, value):
        self._access.engine_factory = value

    async def get(self, ident):
        return await self._access.get(ident)

    async def documents(self, ident):
        return await self._access.documents(ident)

    async def state(self, ident):
        return await self._access.state(ident)

    async def read_json(self, ident, name):
        return await self._access.read_json(ident, name)

    async def read_text(self, ident, name):
        return await self._access.read_text(ident, name)

    async def engine(self, ident, meter=None):
        return await self._access.engine(ident, meter)

    async def allowed(self, ident):
        return await self._jobs.allowed(ident)

    async def summary(self, ident):
        return await self._jobs.summary(ident)

    async def public(self, ident):
        return await self._jobs.public(ident)

    async def document(self, ident, step_id, *, meter=None):
        return await self._documents.document(ident, step_id, meter=meter)

    async def step(self, ident: str, step_id: str):
        return await self._documents.step(ident, step_id)

    async def implementation_package(self, ident, params, *, read_file=False):
        return await self._documents.implementation_package(ident, params, read_file=read_file)

    async def requirement_review(self, ident, params):
        return await self._requirements.requirement_review(ident, params)

    async def impact_context(self, params):
        return await self._impact.impact_context(params)

    async def impact(self, params):
        return await self._impact.impact(params)

    async def cached_impact(self, params, request_key):
        return await self._impact.cached_impact(params, request_key)

    async def _impact_result(self, params, report):
        return await self._impact._impact_result(params, report)

    async def impact_analyse(self, ident, params, request_key, *, meter=None):
        return await self._impact.impact_analyse(ident, params, request_key, meter=meter)

    async def _impact_analyse(self, ident, params, request_key, *, meter=None):
        return await self._impact._impact_analyse(ident, params, request_key, meter=meter)

    async def knowledge_call(self, method: str, params: dict):
        return await self._projects.knowledge_call(method, params)

    async def decision_candidates(self, ident, params):
        return await self._projects.decision_candidates(ident, params)

    async def _validate_reuse_sources(self, items):
        return await self._projects._validate_reuse_sources(items)

    async def project_decisions(self, params):
        return await self._projects.project_decisions(params)
