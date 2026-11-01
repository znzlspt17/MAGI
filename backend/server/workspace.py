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

    def get(self, ident):
        return self._access.get(ident)

    def documents(self, ident):
        return self._access.documents(ident)

    def state(self, ident):
        return self._access.state(ident)

    def read_json(self, ident, name):
        return self._access.read_json(ident, name)

    def read_text(self, ident, name):
        return self._access.read_text(ident, name)

    def engine(self, ident, meter=None):
        return self._access.engine(ident, meter)

    def allowed(self, ident):
        return self._jobs.allowed(ident)

    def summary(self, ident):
        return self._jobs.summary(ident)

    def public(self, ident):
        return self._jobs.public(ident)

    def document(self, ident, step_id, language, *, meter=None):
        return self._documents.document(ident, step_id, language, meter=meter)

    def step(self, ident: str, step_id: str):
        return self._documents.step(ident, step_id)

    def implementation_package(self, ident, params, *, read_file=False):
        return self._documents.implementation_package(ident, params, read_file=read_file)

    def requirement_review(self, ident, params):
        return self._requirements.requirement_review(ident, params)

    def impact_context(self, params):
        return self._impact.impact_context(params)

    def impact(self, params):
        return self._impact.impact(params)

    def cached_impact(self, params, request_key):
        return self._impact.cached_impact(params, request_key)

    def _impact_result(self, params, report):
        return self._impact._impact_result(params, report)

    def impact_analyse(self, ident, params, request_key, *, meter=None):
        return self._impact.impact_analyse(ident, params, request_key, meter=meter)

    def _impact_analyse(self, ident, params, request_key, *, meter=None):
        return self._impact._impact_analyse(ident, params, request_key, meter=meter)

    def knowledge_call(self, method: str, params: dict):
        return self._projects.knowledge_call(method, params)

    def decision_candidates(self, ident, params):
        return self._projects.decision_candidates(ident, params)

    def _validate_reuse_sources(self, items):
        return self._projects._validate_reuse_sources(items)

    def project_decisions(self, params):
        return self._projects.project_decisions(params)
