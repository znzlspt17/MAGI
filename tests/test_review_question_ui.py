"""실제 렌더링 함수를 DOM 모형에서 실행해 부분 답변 제출을 검증한다."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_review_question_context_and_partial_submission():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the frontend check")
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('frontend/static/app.js', 'utf8');
class Element {
    constructor(tag, text = '') { this.tag = tag; this.text = text; this.children = []; this.attrs = {}; this.handlers = {}; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    setAttribute(key, value) { this.attrs[key] = value; }
    addEventListener(key, fn) { this.handlers[key] = fn; }
    get allText() { return [this.text, ...this.children.map(child => child.allText)].join('\n'); }
    set innerHTML(value) { throw new Error('Review context must use text, not HTML'); }
}
const submitted = [];
const context = vm.createContext({
    document: { createElement: tag => new Element(tag) },
    documentCreate: (tag, cls, text) => new Element(tag, text),
    createButton: text => new Element('button', text),
    isCurrentNode: () => true,
    actionableStatus: job => job.status,
    elements: { actions: new Element('div') },
    actionSignature: '', selectedStepId: 'waiting', answerDrafts: new Map(),
    performAction: (id, action, payload) => submitted.push({ id, action, payload }),
    setNotice: () => { throw new Error('Unexpected empty submission'); },
    questionRow: raw => {
        const row = new Element('span', raw);
        const title = new Element('span', raw);
        row.append(title);
        row.querySelector = selector => selector === '.question-title' ? title : null;
        return row;
    },
});
const details = source.slice(source.indexOf('function questionDetails('), source.indexOf('function questionRow('));
const renderer = source.slice(source.indexOf('function reviewQuestionContext('), source.indexOf('function renderSelectedJob('));
vm.runInContext(details + '\n' + renderer, context);
const first = { requirement_ids: ['REQ-005'], missing_information: ['재사용 조건이 미정입니다.'], resolution_reasons: ['사용자 동작을 결정해야 합니다.'], question_id: 'REVIEW-A', question: '메모를 며칠 동안 보관하나요?', problems: ['보관 기간이 미정입니다.'],
    required_changes: ['자동 삭제 동작을 확정해야 합니다.'], evidence: [{ source: 'draft', quote: '<img src=x onerror=alert(1)>' }] };
const second = { ...first, question_id: 'REVIEW-B', question: '백업이 필요한가요?' };
const job = { id: 'fixture', status: 'NEEDS_USER_INPUT', state: { awaiting_input_reason: 'review',
    blocking_questions: [first, second].map(q => `[${q.question_id}] ${q.question}`), review_questions: [first, second], saved_answers: [] } };
context.renderActions(job);
const panel = context.elements.actions.children[0];
assert.match(panel.allText, /요구사항 확인 필요/);
assert.match(panel.allText, /검토에서 발견한 문제: 보관 기간이 미정입니다/);
assert.match(panel.allText, /확인이 필요한 이유: 자동 삭제 동작/);
assert.match(panel.allText, /관련 요구사항: REQ-005/);
assert.match(panel.allText, /미확정 내용: 재사용 조건/);
assert.match(panel.allText, /결정이 필요한 이유: 사용자 동작/);
assert.match(panel.allText, /<img src=x onerror=alert\(1\)>/);
const textarea = panel.children.find(child => child.tag === 'label').children.find(child => child.tag === 'textarea');
assert.equal(textarea.attrs['aria-describedby'], 'question-answer-0-context');
textarea.value = '30일';
textarea.handlers.input();
panel.children.find(child => child.tag === 'button').handlers.click();
assert.equal(submitted.length, 1);
assert.equal(submitted[0].action, 'answer');
assert.equal(submitted[0].payload.length, 1);
assert.equal(submitted[0].payload[0].question_id, 'REVIEW-A');
assert.equal(submitted[0].payload[0].answer, '30일');
job.state.blocking_questions = [`[${second.question_id}] ${second.question}`];
job.state.saved_answers = submitted[0].payload;
context.renderActions(job);
assert.match(context.elements.actions.allText, /요구사항 확인 필요 · 1개/);
assert.doesNotMatch(context.elements.actions.allText, /메모를 며칠 동안 보관하나요/);
"""
    result = subprocess.run([node, "-"], input=script, text=True, encoding="utf-8",
                            cwd=Path(__file__).resolve().parents[1], capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
