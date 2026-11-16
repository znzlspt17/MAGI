import { useState } from "react";
import { Stack } from "@astryxdesign/core/Stack";
import { Button } from "../../shared/ui/UI";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../../shared/ui/collapsible";
import { restoreDraft } from "./session-drafts";

// 2026-11-15: 각 입력의 정확한 키에 해당하는 백업만 보여 다른 사용자나 질문을 섞지 않는다.
export function DraftRecovery({ draftKey, onRestore, disabled = false, describe = (value: string) => value }: {
  draftKey: string; onRestore: (value: string) => void; disabled?: boolean; describe?: (value: string) => string | null;
}) {
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  let entries: { key: string; label: string }[] = [];
  try {
    const prefix = `draft-backup:${draftKey}`;
    entries = Object.keys(sessionStorage).filter(key => key === prefix || (key.startsWith(prefix + ":") && /^\d+(?::\d+)*$/.test(key.slice(prefix.length + 1)))).flatMap(key => {
      const value = sessionStorage.getItem(key);
      const label = value === null ? null : describe(value);
      return label === null ? [] : [{ key, label }];
    });
  } catch { return null; }
  if (!entries.length) return null;
  return <Collapsible key={revision}><CollapsibleTrigger>이전 작성 내용 복구 ({entries.length})</CollapsibleTrigger>
    <CollapsibleContent>
    {entries.map((entry, index) => <Stack as="section" gap={2} key={entry.key} aria-label={`이전 작성 내용 ${index + 1}`}>
      <p className="chat-message-text">{entry.label || "빈 내용"}</p>
      <Button className="self-start" disabled={disabled} onClick={() => {
        // 2026-11-16: 요청 완료 시 입력을 비우기 전에 백업이 교체되지 않도록 막는다.
        if (disabled) return;
        try { const value = restoreDraft(sessionStorage, draftKey, entry.key); onRestore(value); setError(""); setRevision(value => value + 1); }
        catch { setError("작성 내용을 복구하지 못했습니다. 저장 공간을 확인하고 다시 시도하세요."); }
      }}>이 내용 복구</Button>
    </Stack>)}
    {error && <p role="alert">{error}</p>}
    </CollapsibleContent>
  </Collapsible>;
}
