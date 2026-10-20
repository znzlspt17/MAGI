import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor,within} from '@testing-library/react';
import {QuestionActions} from './QuestionActions';
import type {Job} from './types';
vi.mock('./Auth',()=>({useAuth:()=>({user:{id:'owner'},status:{}})}));
afterEach(cleanup);
beforeEach(()=>sessionStorage.clear());
const forms={
 S:{question_id:'S',question:'운영체제',input_type:'single_choice',options:[{id:'a',label:'Windows'},{id:'b',label:'Linux'}],form_version:'S-v1'},
 M:{question_id:'M',question:'기능',input_type:'multiple_choice',options:[{id:'a',label:'저장'},{id:'b',label:'검색'}],form_version:'M-v1'},
 T:{question_id:'T',question:'추가 설명',input_type:'text',options:[],form_version:'T-v1'},
};
const job=(id='first'):Job=>({id,status:'NEEDS_USER_INPUT',state:{blocking_questions:['[S] 운영체제','[M] 기능','[T] 추가 설명'],question_forms:forms,saved_answers:[]}});
const group=(name:string)=>within(screen.getByRole('group',{name:new RegExp(name)}));
describe('질문 답변',()=>{
 it('선택과 직접 입력을 검증하고 답변한 질문만 전송한다',async()=>{
  const action=vi.fn().mockResolvedValue(undefined);
  render(<QuestionActions job={job()} onAction={action} busy={false}/>);
  expect(screen.getAllByRole('radio').some(e=>(e as HTMLInputElement).checked)).toBe(false);
  fireEvent.click(group('운영체제').getByRole('radio',{name:'Windows'}));
  fireEvent.click(group('기능').getByRole('checkbox',{name:'검색'}));
  fireEvent.click(group('기능').getByRole('checkbox',{name:'직접 입력'}));
  fireEvent.click(screen.getByRole('button',{name:'답변 제출'}));
  expect(action).not.toHaveBeenCalled();
  expect(screen.getByText('직접 입력 내용을 작성해주세요.')).toBeTruthy();
  fireEvent.change(group('기능').getByRole('textbox'),{target:{value:'내보내기'}});
  fireEvent.click(screen.getByRole('button',{name:'답변 제출'}));
  await waitFor(()=>expect(action).toHaveBeenCalledOnce());
  const [kind,answers]=action.mock.calls[0];
  expect(kind).toBe('answer');
  expect(answers).toHaveLength(2);
  expect(answers[0]).toMatchObject({question_id:'S',selected_option_ids:['a'],custom_text:null,form_version:'S-v1'});
  expect(answers[1]).toMatchObject({answer:'검색\n내보내기',selected_option_ids:['b'],custom_text:'내보내기'});
  fireEvent.click(group('운영체제').getByRole('radio',{name:'직접 입력'}));
  expect((group('운영체제').getByRole('radio',{name:'Windows'}) as HTMLInputElement).checked).toBe(false);
 });
 it('작업과 폼 버전별 초안을 분리하고 다시 방문하면 복원한다',async()=>{
  const action=vi.fn().mockResolvedValue(undefined),first=job();
  const view=render(<QuestionActions job={first} onAction={action} busy={false}/>);
  fireEvent.click(group('운영체제').getByRole('radio',{name:'Windows'}));
  view.rerender(<QuestionActions job={job('other')} onAction={action} busy={false}/>);
  await waitFor(()=>expect((group('운영체제').getByRole('radio',{name:'Windows'}) as HTMLInputElement).checked).toBe(false));
  fireEvent.click(group('운영체제').getByRole('radio',{name:'Linux'}));
  view.rerender(<QuestionActions job={first} onAction={action} busy={false}/>);
  await waitFor(()=>expect((group('운영체제').getByRole('radio',{name:'Windows'}) as HTMLInputElement).checked).toBe(true));
  const updated={...first,state:{...first.state,question_forms:{...forms,S:{...forms.S,form_version:'S-v2'}}}};
  view.rerender(<QuestionActions job={updated} onAction={action} busy={false}/>);
  await waitFor(()=>expect((group('운영체제').getByRole('radio',{name:'Windows'}) as HTMLInputElement).checked).toBe(false));
 });
 it('저장한 선택을 복원하고 이전 형식 답변은 직접 입력으로 보존한다',()=>{
  const value=job();value.state!.saved_answers=[{question_id:'S',answer:'Windows',selection:{selected_option_ids:['a'],custom_text:null,form_version:'S-v1'}},{question_id:'M',answer:'과거 답변'}];
  render(<QuestionActions job={value} onAction={vi.fn()} busy={false}/>);
  expect((group('운영체제').getByRole('radio',{name:'Windows'}) as HTMLInputElement).checked).toBe(true);
  expect((group('기능').getByRole('textbox') as HTMLTextAreaElement).value).toBe('과거 답변');
 });
 it('검토 근거를 안전한 텍스트로 표시하고 남은 질문만 보여 준다',async()=>{
  const value:Job={id:'review',status:'NEEDS_USER_INPUT',state:{awaiting_input_reason:'review',blocking_questions:['[A] 보관 기간','[B] 백업 필요'],review_questions:[{question_id:'A',requirement_ids:['REQ-005'],missing_information:['재사용 조건'],resolution_reasons:['사용자 동작'],problems:['보관 기간 미정'],required_changes:['삭제 동작 확정'],evidence:[{source:'draft',quote:'<img src=x onerror=alert(1)>'}]}]}};
  const action=vi.fn().mockResolvedValue(undefined),view=render(<QuestionActions job={value} onAction={action} busy={false}/>);
  for(const text of ['관련 요구사항: REQ-005','미확정 내용: 재사용 조건','결정이 필요한 이유: 사용자 동작','검토에서 발견한 문제: 보관 기간 미정','확인이 필요한 이유: 삭제 동작 확정'])expect(screen.getByText(text)).toBeTruthy();
  expect(screen.getByText(/<img src=x/)).toBeTruthy();expect(view.container.querySelector('img')).toBeNull();
  fireEvent.change(screen.getByRole('textbox',{name:'보관 기간'}),{target:{value:'30일'}});
  await act(async()=>fireEvent.click(screen.getByRole('button',{name:'답변 제출'})));
  expect(action.mock.calls[0][1]).toEqual([{question_id:'A',question:'[A] 보관 기간',answer:'30일'}]);
  view.rerender(<QuestionActions job={{...value,state:{...value.state,blocking_questions:['[B] 백업 필요']}}} onAction={action} busy={false}/>);
  expect(screen.queryByRole('textbox',{name:'보관 기간'})).toBeNull();
 });
});

