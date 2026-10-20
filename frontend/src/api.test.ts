import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {api,clearRequests,configureAuth,post} from './api';
const reply=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
beforeEach(()=>{clearRequests();configureAuth({publicMode:true,csrf:'test-csrf'});});
afterEach(()=>vi.restoreAllMocks());
it('실패한 변경 요청의 수동 재시도는 같은 멱등성 키를 사용한다',async()=>{
 const fetcher=vi.spyOn(globalThis,'fetch').mockRejectedValueOnce(new TypeError('network unavailable')).mockResolvedValueOnce(reply({ok:true}));
 await expect(post('/api/jobs',{request:'test'})).rejects.toThrow();
 await post('/api/jobs',{request:'test'});
 const first=new Headers(fetcher.mock.calls[0][1]?.headers),second=new Headers(fetcher.mock.calls[1][1]?.headers);
 expect(first.get('X-CSRF-Token')).toBe('test-csrf');expect(first.get('Idempotency-Key')).toBeTruthy();expect(first.get('Idempotency-Key')).toBe(second.get('Idempotency-Key'));
 expect(fetcher).toHaveBeenCalledTimes(2);
});
it('5xx 응답은 문의 번호를 안내하고 재시도 키를 보존한다',async()=>{
 const fetcher=vi.spyOn(globalThis,'fetch').mockResolvedValueOnce(reply({error:'작업 확인 필요',request_id:'fake-request-id'},503)).mockResolvedValueOnce(reply({ok:true}));
 await expect(post('/api/jobs',{request:'test'})).rejects.toThrow('문의 번호 fake-request-id');expect(fetcher).toHaveBeenCalledTimes(1);
 await post('/api/jobs',{request:'test'});expect(new Headers(fetcher.mock.calls[0][1]?.headers).get('Idempotency-Key')).toBe(new Headers(fetcher.mock.calls[1][1]?.headers).get('Idempotency-Key'));
});
it('이전 인증의 늦은 401은 현재 인증을 해제하지 않는다',async()=>{
 let finish!:(value:Response)=>void;vi.spyOn(globalThis,'fetch').mockImplementation(()=>new Promise(resolve=>finish=resolve));
 const listener=vi.fn();window.addEventListener('magi:signed-out',listener);
 const request=api('/api/me').catch(()=>{});configureAuth({publicMode:true,csrf:'new-csrf'});finish(reply({error:'expired'},401));await request;
 expect(listener).not.toHaveBeenCalled();window.removeEventListener('magi:signed-out',listener);
});
it('이전 계정의 응답은 새 계정의 재시도 키를 제거하지 않는다',async()=>{
 let finish!:(value:Response)=>void;const fetcher=vi.spyOn(globalThis,'fetch').mockImplementationOnce(()=>new Promise(resolve=>finish=resolve)).mockRejectedValueOnce(new TypeError('network unavailable')).mockResolvedValueOnce(reply({ok:true}));
 const old=post('/api/jobs',{request:'same'});clearRequests();configureAuth({publicMode:true,csrf:'other-csrf'});
 await expect(post('/api/jobs',{request:'same'})).rejects.toThrow();finish(reply({ok:true}));await old;await post('/api/jobs',{request:'same'});
 const second=new Headers(fetcher.mock.calls[1][1]?.headers),third=new Headers(fetcher.mock.calls[2][1]?.headers);expect(second.get('Idempotency-Key')).toBe(third.get('Idempotency-Key'));
});
