import * as React from "react";
// 2026-11-11: 라디오와 체크박스를 감싸는 레이블의 네이티브 연결을 유지한다.
function Label(props: React.ComponentProps<"label">) { return <label {...props} data-slot="label" />; }
export {Label};
