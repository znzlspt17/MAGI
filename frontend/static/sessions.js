/* 세션의 사용자 대화와 문서 이력을 내부 실행 단계와 구분한다. */
(() => {
    const $ = id => document.getElementById(id);
    const previous = window.MagiWorkspace.rendered;
    let signature = '';
    window.MagiWorkspace.rendered = job => {
        previous(job);
        const key = JSON.stringify([job.id, job.session_events, job.latest_completed, job.status]);
        if (key === signature) return;
        signature = key;
        const host = $('session-events');
        const previousTop = host.scrollTop, atBottom = host.scrollHeight - host.scrollTop - host.clientHeight < 40;
        host.replaceChildren();
        function text(tag, content, parent) { const node = document.createElement(tag); node.textContent = content; parent.append(node); return node; }
        for (const event of job.session_events || []) {
            const row = text('section', '', host); row.className = 'session-turn';
            const labels = {generate: '처음 요청', answer: '질문에 답변', revise: '후속·수정 요청', approve: '사용자 승인'};
            text('h4', `${labels[event.action] || event.action} · ${formatTime(event.started_at)}`, row);
            const input = event.input || {};
            const body = input.request || input.feedback || (input.answers || []).map(a => `${a.question}\n${a.answer}`).join('\n\n');
            if (body) text('p', body, row);
            text('small', `${statusLabel(event.status)}${event.summary ? ' · ' + event.summary : ''}`, row);
            if (event.questions?.length) {
                text('h4', 'MAGI · 확인이 필요한 질문', row);
                const list = document.createElement('ol'); row.append(list);
                event.questions.forEach((question, index) => text('li', questionDetails(question, index).label, list));
            }
            if (event.document_step_id) {
                const button = text('button', '이 시점의 명세 열기', row); button.type = 'button';
                button.addEventListener('click', async () => {
                    document.querySelector('button[data-worktab=history]').click();
                    selectedTab = 'document'; await selectStep(event.document_step_id, true);
                });
            }
        }
        if (!host.children.length) text('p', '이 세션에 저장된 대화 이력이 없습니다.', host);
        host.scrollTop = atBottom ? host.scrollHeight : previousTop;
        const documents = $('completed-documents'); documents.replaceChildren();
        text('span', job.status === 'FINALIZED' ? '최근 완료본' : job.latest_completed ? '현재 작업 중인 초안 · 이전 완료본은 별도 보존됩니다.' : '아직 승인된 완료 명세가 없습니다.', documents);
        if (job.latest_completed?.step_id) {
            const button = text('button', job.status === 'FINALIZED' ? '최근 완료 명세 열기' : '이전 완료본 열기', documents); button.type = 'button';
            button.addEventListener('click', async () => {
                document.querySelector('button[data-worktab=history]').click();
                selectedTab = 'document'; await selectStep(job.latest_completed.step_id, true);
            });
        }
        if (job.completed_documents?.length > 1) {
            const label = text('label', '보존된 완료 명세 ', documents);
            const select = document.createElement('select'); select.setAttribute('aria-label', '보존된 완료 명세'); label.append(select);
            job.completed_documents.forEach((item, index) => { const option = text('option', `완료본 ${index + 1}`, select); option.value = item.id; });
            const open = text('button', '선택한 완료본 열기', documents); open.type = 'button';
            open.addEventListener('click', async () => {
                document.querySelector('button[data-worktab=history]').click();
                selectedTab = 'document'; await selectStep(select.value, true);
            });
        }
    };
    document.addEventListener('magi:cleanup', () => { signature = ''; if (!selectedId) { $('session-events').replaceChildren(); $('completed-documents').replaceChildren(); } });
})();
