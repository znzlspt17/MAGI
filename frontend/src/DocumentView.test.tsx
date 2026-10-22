import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {DocumentView} from './DocumentView';
import {post} from './api';
vi.mock('./api',()=>({post:vi.fn(),api:vi.fn().mockResolvedValue({status:'unavailable',message:'기준 없음'})}));
afterEach(()=>{cleanup();vi.restoreAllMocks();});
beforeEach(()=>vi.mocked(post).mockReset());
const english={content:'# English document',filename:'spec.en.md',source_hash:'snapshot'};
const korean={content:'# 한국어 문서',filename:'spec.ko.md',source_hash:'snapshot',language:'ko'};
function deferred(){let resolve!:(v:any)=>void,reject!:(v:any)=>void;const promise=new Promise<any>((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};}
const click=(name:string)=>fireEvent.click(screen.getByRole('button',{name}));
const blobText=(blob:Blob)=>new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=reject;reader.readAsText(blob);});
const download=()=>screen.getByRole('button',{name:'Markdown 다운로드'}) as HTMLButtonElement;
it('근거표만 열면 번역 생성과 모델 호출을 시작하지 않는다',async()=>{
 const open=vi.fn();
 render(<DocumentView jobId="job" stepId="one" document={{...english,kind:'candidate'}} reviewOnly onShowDocument={open}/>);
 await screen.findByText('기준 없음');
 expect(post).not.toHaveBeenCalled();
 expect(screen.queryByRole('button',{name:'Markdown 다운로드'})).toBeNull();
 click('명세 문서 보기');expect(open).toHaveBeenCalledOnce();
});
it('늦게 도착한 번역은 영어 선택을 유지하고 캐시와 다운로드는 선택 언어를 따른다',async()=>{
 const pending=deferred();vi.mocked(post).mockReturnValue(pending.promise);
 const blobs:Blob[]=[],links:HTMLAnchorElement[]=[];
 Object.defineProperty(URL,'createObjectURL',{configurable:true,value:vi.fn((blob:Blob)=>{blobs.push(blob);return'blob:test';})});
 Object.defineProperty(URL,'revokeObjectURL',{configurable:true,value:vi.fn()});
 vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function(this:HTMLAnchorElement){links.push(this);});
 const view=render(<DocumentView jobId="job" stepId="one" document={english}/>);
 expect(download().disabled).toBe(true);
 click('English');await screen.findByRole('heading',{name:'English document'});
 click('Markdown 다운로드');expect(links[0].download).toBe('spec.en.md');expect(await blobText(blobs[0])).toBe(english.content);
 await act(async()=>pending.resolve(korean));
 expect(screen.getByRole('heading',{name:'English document'})).toBeTruthy();
 click('한국어');await screen.findByRole('heading',{name:'한국어 문서'});
 expect(post).toHaveBeenCalledTimes(1);
 click('Markdown 다운로드');expect(links[1].download).toBe('spec.ko.md');expect(await blobText(blobs[1])).toBe(korean.content);
 click('Markdown 보기');expect(view.container.querySelector('pre')?.textContent).toBe(korean.content);
 click('English');await waitFor(()=>expect(view.container.querySelector('pre')?.textContent).toBe(english.content));
 click('Markdown 다운로드');expect(await blobText(blobs[2])).toBe(english.content);
 click('한국어');await waitFor(()=>expect(view.container.querySelector('pre')?.textContent).toBe(korean.content));
 view.rerender(<DocumentView jobId="job" stepId="one" document={{...english}}/>);
 expect(post).toHaveBeenCalledTimes(1);
});
it('이전 단계의 번역 응답이 최신 단계를 덮어쓰지 않는다',async()=>{
 const old=deferred(),latest=deferred();vi.mocked(post).mockReturnValueOnce(old.promise).mockReturnValueOnce(latest.promise);
 const view=render(<DocumentView jobId="job" stepId="old" document={english}/>);
 view.rerender(<DocumentView jobId="job" stepId="latest" document={{...english,content:'# New snapshot'}}/>);
 await act(async()=>old.resolve({...korean,content:'# 과거 명세'}));expect(download().disabled).toBe(true);expect(screen.queryByText('과거 명세')).toBeNull();
 await act(async()=>latest.resolve({...korean,content:'# 최신 명세'}));await screen.findByRole('heading',{name:'최신 명세'});
});
it('번역 실패, 재시도 및 원문 해시 불일치를 표시하며 다운로드를 막는다',async()=>{
 vi.mocked(post).mockRejectedValueOnce(new Error('번역 실패')).mockResolvedValueOnce(korean).mockResolvedValueOnce({...korean,source_hash:'different'});
 const view=render(<DocumentView jobId="job" stepId="failure" document={english}/>);
 await screen.findByText(/준비하지 못했습니다/);expect(download().disabled).toBe(true);
 click('English');await screen.findByRole('heading',{name:'English document'});expect(download().disabled).toBe(false);
 click('한국어');await screen.findByRole('heading',{name:'한국어 문서'});
 view.rerender(<DocumentView jobId="job" stepId="changed" document={english}/>);
 await screen.findByText(/원문이 변경되었습니다/);expect(download().disabled).toBe(true);
});
it('실패한 한국어본을 명시적으로 다시 생성한다',async()=>{
 vi.mocked(post).mockRejectedValueOnce(new Error('번역 실패')).mockResolvedValueOnce(korean);
 render(<DocumentView jobId="job" stepId="retry" document={english}/>);
 await screen.findByText(/준비하지 못했습니다/);click('한국어본 다시 생성');
 await screen.findByRole('heading',{name:'한국어 문서'});expect(download().disabled).toBe(false);expect(post).toHaveBeenCalledTimes(2);
});
