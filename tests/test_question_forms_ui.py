"""실제 브라우저에서 공통 질문 폼과 초안·부분 제출을 확인한다."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_choice_forms_in_browser():
    node = shutil.which("node")
    packages = Path(node).parent.parent / "node_modules" if node else Path("/missing")
    if not (packages / "playwright").is_dir():
        pytest.skip("Playwright 런타임이 없습니다.")
    script = r"""
const fs = require('node:fs'), {createRequire} = require('node:module'), assert = require('node:assert/strict');
const {chromium} = createRequire(process.argv[2] + '/package.json')('playwright');
(async () => {
 let browser;
 try { browser = await chromium.launch({headless:true}); }
 catch(e) { if (!e.message.includes("Executable doesn't exist")) throw e; browser = await chromium.launch({headless:true, channel:'msedge'}); }
 try {
  const page = await browser.newPage({viewport:{width:1200,height:900}});
  const source = fs.readFileSync('frontend/static/app.js','utf8');
  const errors=[]; page.on('pageerror', e=>errors.push(e.message));
  await page.setContent('<main id="actions"></main>');
  await page.addStyleTag({path:'frontend/static/styles.css'});
  await page.addScriptTag({content: `
   window.answerDrafts=new Map(); window.actionSignature=''; window.selectedStepId='waiting';
   window.elements={actions:document.getElementById('actions')};
   window.isCurrentNode=()=>true; window.actionableStatus=j=>j.status;
   window.documentCreate=(tag, cls, text)=>{const e=document.createElement(tag); if(cls)e.className=cls; if(text)e.textContent=text; return e};
   window.createButton=t=>documentCreate('button',null,t);
   window.submitted=[]; window.performAction=(id,action,payload)=>submitted.push(payload); window.setNotice=()=>{};
  ` + source.slice(source.indexOf('function questionDetails('),source.indexOf('function questionRow('))
    + source.slice(source.indexOf('function questionFormDraft('),source.indexOf('function renderSelectedJob('))});
  await page.evaluate(()=>{
   const forms={};
   for(const [id,type,title] of [['S','single_choice','운영체제'],['M','multiple_choice','기능'],['T','text','추가 설명']])
    forms[id]={question_id:id,question:title,input_type:type,options:type==='text'?[]:[{id:'a',label:id==='S'?'Windows':'저장'},{id:'b',label:id==='S'?'Linux':'검색'}],form_version:id+'-v1'};
   window.job={id:'job1',status:'NEEDS_USER_INPUT',state:{blocking_questions:Object.values(forms).map(f=>'['+f.question_id+'] '+f.question),question_forms:forms,saved_answers:[]}};
   renderActions(job);
  });
  assert.equal(await page.locator('input:checked').count(),0);
  const single=page.getByRole('group',{name:'운영체제',exact:true});
  await single.getByRole('radio',{name:'Windows',exact:true}).check();
  const multi=page.getByRole('group',{name:'기능',exact:true});
  await multi.getByRole('checkbox',{name:'검색',exact:true}).check();
  await multi.getByRole('checkbox',{name:'직접 입력',exact:true}).check();
  await page.getByRole('button',{name:'답변 제출',exact:true}).click();
  assert.equal(await page.evaluate(()=>submitted.length),0);
  await multi.getByRole('textbox').fill('내보내기');
  await page.evaluate(()=>{actionSignature='';renderActions(job)});
  assert.equal(await single.getByRole('radio',{name:'Windows',exact:true}).isChecked(),true);
  assert.equal(await multi.getByRole('textbox').inputValue(),'내보내기');
  await page.evaluate(()=>{const other={...job,id:'job2'};renderActions(other);renderActions(job)});
  assert.equal(await single.getByRole('radio',{name:'Windows',exact:true}).isChecked(),true);
  await page.getByRole('button',{name:'답변 제출',exact:true}).click();
  const payload=await page.evaluate(()=>submitted[0]);
  assert.equal(payload.length,2); assert.deepEqual(payload[0].selected_option_ids,['a']);
  assert.equal(payload[1].answer,'검색\n내보내기');
  await single.getByRole('radio',{name:'직접 입력',exact:true}).check();
  await single.getByRole('textbox').fill('macOS');
  assert.equal(await single.getByRole('radio',{name:'Windows',exact:true}).isChecked(),false);
  await page.evaluate(()=>{answerDrafts.clear(); job.state.saved_answers=[{question_id:'S',answer:'과거 답변'}];actionSignature='';renderActions(job)});
  assert.equal(await single.getByRole('textbox').inputValue(),'과거 답변');
  await page.evaluate(()=>{answerDrafts.clear();job.state.saved_answers=[{question_id:'S',answer:'Windows',selection:{selected_option_ids:['a'],custom_text:null,form_version:'S-v1'}}];actionSignature='';renderActions(job)});
  assert.equal(await single.getByRole('radio',{name:'Windows',exact:true}).isChecked(),true);
  await single.getByRole('radio',{name:'Windows',exact:true}).focus();
  await page.keyboard.press('ArrowDown');
  assert.equal(await single.getByRole('radio',{name:'Linux',exact:true}).isChecked(),true);
  await page.screenshot({path:'.pytest_cache/question-forms-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:'.pytest_cache/question-forms-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
"""
    result = subprocess.run([node, "-", str(packages)], input=script, text=True,
                            encoding="utf-8", capture_output=True, timeout=60,
                            cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 0, result.stdout + result.stderr
