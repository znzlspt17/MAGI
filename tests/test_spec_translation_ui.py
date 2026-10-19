"""실제 명세 렌더러를 DOM 모형에서 실행해 언어와 다운로드 일치를 확인한다."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_language_switch_download_races_and_translation_failures():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the frontend check")
    script = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('frontend/static/app.js', 'utf8');
const downloads = [], blobs = new Map(), requests = [];
class Element {
    constructor(tag, text = '') {
        this.tag = tag; this.textContent = text; this.children = []; this.attrs = {}; this.handlers = {};
        this.classList = { toggle() {} };
    }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; this.rendered = ''; }
    setAttribute(key, value) { this.attrs[key] = value; }
    addEventListener(key, fn) { this.handlers[key] = fn; }
    click() {
        if (this.tag === 'a') downloads.push({ name: this.download, blob: blobs.get(this.href) });
        else return this.handlers.click?.();
    }
}
const context = vm.createContext({
    Blob,
    URL: { createObjectURL(blob) { const key = `blob:${blobs.size}`; blobs.set(key, blob); return key; }, revokeObjectURL() {} },
    setTimeout: fn => fn(),
    document: { createElement: tag => new Element(tag) },
    documentCreate: (tag, cls, text) => new Element(tag, text),
    renderMarkdown: (view, content) => { view.replaceChildren(); view.rendered = content; },
    elements: { detailContent: new Element('div') },
    selectedJob: { id: 'job' }, selectedStepId: 'step-1', selectedTab: 'document',
    documentLanguage: 'ko', documentViewMode: 'rendered', documentRequestSequence: 0,
    documentTranslations: new Map(),
    api: (path, options) => new Promise((resolve, reject) => requests.push({ path, options, resolve, reject })),
});
vm.runInContext(source.slice(source.indexOf('function renderDocument('), source.indexOf('function renderMarkdown(')), context);
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
const parts = () => {
    const [controls, note, view] = context.elements.detailContent.children;
    return { buttons: controls.children, note, view };
};
const english = { content: '# English document', filename: 'approval_candidate_spec.en.md' };
const korean = { content: '# 한국어 문서', language: 'ko', filename: 'approval_candidate_spec.ko.md' };
(async () => {
    context.renderDocument(english);
    let { buttons, note, view } = parts();
    assert.equal(requests.length, 1);
    assert.equal(JSON.parse(requests[0].options.body).language, 'ko');
    assert.equal(buttons[4].disabled, true);
    buttons[4].click();
    assert.equal(downloads.length, 0);
    await buttons[1].click();
    assert.equal(view.rendered, english.content);
    buttons[4].click();
    assert.equal(downloads[0].name, english.filename);
    assert.equal(await downloads[0].blob.text(), english.content);
    requests[0].resolve(korean);
    await flush();
    assert.equal(view.rendered, english.content, 'A late Korean response must not replace the selected English view');
    await buttons[0].click();
    assert.equal(view.rendered, korean.content);
    assert.equal(requests.length, 1);
    buttons[4].click();
    assert.equal(downloads[1].name, korean.filename);
    assert.equal(await downloads[1].blob.text(), korean.content);
    buttons[3].click();
    assert.equal(view.children[0].textContent, korean.content);
    await buttons[1].click();
    assert.equal(view.children[0].textContent, english.content);
    buttons[4].click();
    assert.equal(await downloads[2].blob.text(), english.content);
    await buttons[0].click();
    context.elements.detailContent.replaceChildren();
    context.renderDocument(english);
    await flush();
    assert.equal(requests.length, 1, 'Rerendering must reuse the same saved translation');
    context.selectedStepId = 'step-2';
    context.elements.detailContent.replaceChildren();
    context.renderDocument({ ...english, content: '# Old snapshot' });
    context.selectedStepId = 'step-3';
    context.elements.detailContent.replaceChildren();
    context.renderDocument({ ...english, content: '# New snapshot' });
    const newest = parts();
    requests[1].resolve({ ...korean, content: '# 과거 명세' });
    await flush();
    assert.equal(newest.buttons[4].disabled, true);
    requests[2].resolve({ ...korean, content: '# 최신 명세' });
    await flush();
    assert.equal(newest.view.children[0].textContent, '# 최신 명세');
    context.selectedStepId = 'step-4';
    context.elements.detailContent.replaceChildren();
    context.renderDocument(english);
    requests[3].reject(new Error('번역 실패'));
    await flush();
    ({ buttons, note, view } = parts());
    assert.match(note.textContent, /준비하지 못했습니다/);
    assert.equal(buttons[4].disabled, true);
    assert.equal(buttons[5].hidden, false);
    await buttons[1].click();
    assert.equal(buttons[4].disabled, false);
    assert.equal(view.children[0].textContent, english.content);
    buttons[5].click();
    assert.equal(buttons[4].disabled, true);
    assert.equal(requests.length, 5);
    requests[4].resolve(korean);
    await flush();
    buttons[4].click();
    assert.equal(await downloads[3].blob.text(), korean.content);
    context.selectedStepId = 'step-5';
    context.elements.detailContent.replaceChildren();
    context.renderDocument({ ...english, source_hash: 'expected-snapshot' });
    requests[5].resolve({ ...korean, source_hash: 'different-snapshot' });
    await flush();
    const changed = parts();
    assert.equal(changed.buttons[4].disabled, true);
    assert.match(changed.note.textContent, /원문이 변경되었습니다/);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    result = subprocess.run([node, "-"], input=script, text=True, encoding="utf-8",
                            cwd=Path(__file__).resolve().parents[1], capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
