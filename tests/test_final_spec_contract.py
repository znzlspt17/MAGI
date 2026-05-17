from __future__ import annotations

from pathlib import Path


REQUIRED_HEADINGS = [
    "# Final Agent Specification",
    "## 1. Mission",
    "## 2. Background",
    "## 3. User Intent",
    "## 4. Scope",
    "### 4.1 In Scope",
    "### 4.2 Out of Scope",
    "## 5. Definitions",
    "## 6. Evidence Summary",
    "## 7. Mandatory Requirements",
    "## 8. Recommended Requirements",
    "## 9. Optional Requirements",
    "## 10. Forbidden Behaviors",
    "## 11. Input Contract",
    "## 12. Output Contract",
    "## 13. Architecture",
    "## 14. Module Responsibilities",
    "## 15. Data Flow",
    "## 16. Error Handling Policy",
    "## 17. Configuration Policy",
    "## 18. Persistence / Artifact Policy",
    "## 19. Implementation Order",
    "## 20. Acceptance Criteria",
    "## 21. Test Plan",
    "## 22. Manual Verification Checklist",
    "## 23. Instructions for AI Coding Agent",
]


def test_final_spec_contract_after_approval(mock_engine, tmp_path: Path) -> None:
    output = tmp_path / "out"
    mock_engine.generate_from_text(
        text="한국어 요청도 최종 명세에는 영어만 있어야 한다.",
        output_dir=str(output),
        web_search_mode="off",
    )
    mock_engine.approve(str(output))
    final_text = (output / "final" / "FINAL_AGENT_SPEC.md").read_text(encoding="utf-8")

    for heading in REQUIRED_HEADINGS:
        assert heading in final_text
    assert not any("\uac00" <= char <= "\ud7a3" for char in final_text)
