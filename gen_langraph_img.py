from magi_spec.core.config import MagiConfig
from magi_spec.core.artifacts import ArtifactWriter
from magi_spec.core.evidence import EvidenceRegistry
from magi_spec.skills.registry import build_default_skill_registry
from magi_spec.providers import default_provider_factory
from magi_spec.graph.nodes import WorkflowNodes
from magi_spec.pipeline.builder import build_v2_workflow
import tempfile, os

config = MagiConfig.mock()
with tempfile.TemporaryDirectory() as tmp:
    writer = ArtifactWriter(tmp)
    writer.prepare()
    nodes = WorkflowNodes(
        writer=writer,
        config=config,
        providers=default_provider_factory(),
        skills=build_default_skill_registry(),
        evidence=EvidenceRegistry(),
    )
    workflow = build_v2_workflow(nodes)
    img = workflow.get_graph().draw_mermaid_png()
    out = r'C:\Project\MAGI.worktrees\agents-plan-agent-invocation\docs\specforge_pipeline.png'
    with open(out, 'wb') as f:
        f.write(img)
    print('saved:', out)

    