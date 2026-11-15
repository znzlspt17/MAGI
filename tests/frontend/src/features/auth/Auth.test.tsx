import {StrictMode} from 'react';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {AuthProvider,useAuth} from '@/features/auth/Auth';
import {api,post,configureAuth,ApiError} from '@/shared/api/api';
vi.mock('@/shared/api/api',async importOriginal=>({...(await importOriginal<typeof import('@/shared/api/api')>()),api:vi.fn(),post:vi.fn().mockResolvedValue({}),configureAuth:vi.fn(),clearRequests:vi.fn()}));
function Account(){const auth=useAuth();return <><p>{auth.user?.id}</p><p>{auth.status.active_count?'busy':'available'}</p><p>{auth.status.checkState}</p><p>{auth.status.own_active_count?'mine':'not-mine'}</p><button onClick={()=>void auth.logout()}>logout</button></>;}
it('다른 탭에서 연결된 같은 계정만 현재 탭의 익명 초안을 이어받는다',async()=>{
 let linked=false;
 const original=vi.mocked(api).getMockImplementation()!;
 vi.mocked(api).mockImplementation((path,...args)=>path==='/api/me'
   ? Promise.resolve(linked?{id:'owner',role:'user',csrf:'new',identity_kind:'google',owner_ids:['owner','guest']}:{id:'guest',role:'user',csrf:'old',identity_kind:'guest',owner_ids:['guest']})
   :original(path,...args));
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('guest');
 sessionStorage.setItem('draft:guest:job:message','작성 중');
 linked=true;act(()=>window.dispatchEvent(new Event('signed-out')));
 await screen.findByText('owner');
 expect(sessionStorage.getItem('draft:owner:job:message')).toBe('작성 중');
 expect(sessionStorage.getItem('draft:guest:job:message')).toBeNull();
});
it('서버가 이전 익명 사용자를 연결하지 않은 다른 계정에는 초안을 옮기지 않는다',async()=>{
 let switched=false;
 const original=vi.mocked(api).getMockImplementation()!;
 vi.mocked(api).mockImplementation((path,...args)=>path==='/api/me'
   ? Promise.resolve(switched?{id:'other',role:'user',csrf:'new',identity_kind:'google',owner_ids:['other']}:{id:'guest',role:'user',csrf:'old',identity_kind:'guest',owner_ids:['guest']})
   :original(path,...args));
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('guest');
 sessionStorage.setItem('draft:guest:job:message','작성 중');
 switched=true;act(()=>window.dispatchEvent(new Event('signed-out')));
 await screen.findByText('other');
 expect(sessionStorage.getItem('draft:other:job:message')).toBeNull();
 expect(sessionStorage.getItem('draft:guest:job:message')).toBeNull();
});
it('세션이 갱신되어도 같은 사용자 ID의 초안을 지우지 않는다',async()=>{
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');
 sessionStorage.setItem('draft:owner','유지할 초안');
 act(()=>window.dispatchEvent(new Event('signed-out')));
 await screen.findByText('owner');
 expect(sessionStorage.getItem('draft:owner')).toBe('유지할 초안');
});
it('숨겨진 탭의 실시간 상태 이벤트는 HTTP 요청 없이 상태를 갱신한다',async()=>{
 let visible: DocumentVisibilityState='visible';vi.spyOn(document,'visibilityState','get').mockImplementation(()=>visible);
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');await screen.findByText('ready');
 visible='hidden';
 const calls=vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status').length;
 const usageCalls=vi.mocked(api).mock.calls.filter(([path])=>path==='/api/me/usage').length;
 act(()=>window.dispatchEvent(new CustomEvent('service-status',{detail:{ready:true,active_count:2,own_active_count:1}})));
 act(()=>window.dispatchEvent(new CustomEvent('realtime-connection',{detail:{connected:true}})));
 expect(screen.getByText('busy')).toBeTruthy();expect(screen.getByText('mine')).toBeTruthy();
 expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status')).toHaveLength(calls);
 expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/api/me/usage')).toHaveLength(usageCalls);
});
beforeEach(()=>{Object.defineProperty(navigator,'locks',{configurable:true,value:{request:(_name:string, callback:()=>unknown)=>callback()}});vi.mocked(post).mockReset().mockResolvedValue({});vi.mocked(api).mockImplementation(async(path:string)=>path==='/api/auth/info'?{public:true,login_available:true}:path==='/api/me'?{id:'owner',role:'user',csrf:'fake-csrf',identity_kind:'google'}:path==='/api/service/status'?{ready:true,active_count:0,own_active_count:0}:{runs:1,remaining_runs:3});sessionStorage.clear();});
it('잠금이 없으면 익명 세션을 안전하지 않게 발급하지 않는다',async()=>{
 Object.defineProperty(navigator,'locks',{configurable:true,value:undefined});
 vi.mocked(api).mockImplementation(async path=>{if(path==='/api/auth/info')return {public:true};throw new ApiError('expired',401);});
 render(<AuthProvider><Account/></AuthProvider>);
 expect((await screen.findByRole('alert')).textContent).toContain('브라우저');
 expect(post).not.toHaveBeenCalled();
});
afterEach(()=>{cleanup();vi.useRealTimers();vi.clearAllMocks();vi.restoreAllMocks();history.replaceState(null,'','/');});
it('미로그인 방문자는 익명 세션으로 바로 작업 공간을 연다',async()=>{
 let created=false;
 vi.mocked(post).mockImplementation(async path=>{if(path==='/api/auth/guest') created=true;return {};});
 vi.mocked(api).mockImplementation(async path=>{
  if(path==='/api/auth/info')return {public:true,login_available:false};
  if(path==='/api/me') {if(!created) throw new ApiError('로그인이 필요합니다.',401);return {id:'guest-id',role:'user',csrf:'guest-csrf',identity_kind:'guest'};}
  return path==='/api/service/status'?{ready:true,active_count:0,own_active_count:0}:{runs:0};
 });
 render(<AuthProvider><Account/></AuthProvider>);
 expect(await screen.findByText('guest-id')).toBeTruthy();
 expect(post).toHaveBeenCalledWith('/api/auth/guest',{});
 expect(vi.mocked(post).mock.calls.filter(([path])=>path==='/api/auth/guest')).toHaveLength(1);
 expect(configureAuth).toHaveBeenCalledWith({publicMode:true,csrf:'guest-csrf'});
 expect(screen.queryByRole('link',{name:'Google로 로그인'})).toBeNull();
});
it('기존 익명 사용자의 세션 만료일을 작업 공간을 열기 전에 갱신한다',async()=>{
 let finish!:()=>void;
 vi.mocked(post).mockImplementation(path=>path==='/api/auth/guest'?new Promise(resolve=>{finish=()=>resolve({});}):Promise.resolve({}));
 const original=vi.mocked(api).getMockImplementation()!;
 vi.mocked(api).mockImplementation((path,...args)=>path==='/api/me'?Promise.resolve({id:'guest-id',role:'user',csrf:'guest-csrf',identity_kind:'guest'}):original(path,...args));
 render(<AuthProvider><Account/></AuthProvider>);
 await waitFor(()=>expect(post).toHaveBeenCalledWith('/api/auth/guest',{}));
 expect(screen.queryByText('guest-id')).toBeNull();
 await act(async()=>finish());
 expect(await screen.findByText('guest-id')).toBeTruthy();
 expect(vi.mocked(post).mock.calls.filter(([path])=>path==='/api/auth/guest')).toHaveLength(1);
});
it('기존 세션은 익명 세션을 다시 발급하지 않는다',async()=>{
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');
 expect(vi.mocked(post).mock.calls.some(([path])=>path==='/api/auth/guest')).toBe(false);
});
it('계정 연결 성공 시 현재 작업과 익명 초안을 복원한다',async()=>{
 const path='/jobs/'+'a'.repeat(32);
 history.replaceState(null,'','/?auth=linked');
 sessionStorage.setItem('magi-account-link',JSON.stringify({owner:'guest',path}));
 sessionStorage.setItem('draft:guest','새 요청');sessionStorage.setItem('draft:guest:'+ 'a'.repeat(32)+':message','작성 중');
 sessionStorage.setItem('draft:owner','기존 계정 초안');
 const original=vi.mocked(api).getMockImplementation()!;
 vi.mocked(api).mockImplementation((path,...args)=>path==='/api/me'?Promise.resolve({id:'owner',role:'user',csrf:'fake-csrf',identity_kind:'google',owner_ids:['owner','guest']}):original(path,...args));
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');
 expect(location.pathname).toBe(path);
 expect(sessionStorage.getItem('draft:owner')).toBe('새 요청');
 expect(sessionStorage.getItem('draft:guest')).toBeNull();
 expect(sessionStorage.getItem('draft:owner:'+ 'a'.repeat(32)+':message')).toBe('작성 중');
 expect(sessionStorage.getItem('draft-backup:draft:owner')).toBe('기존 계정 초안');
});
it('오래된 연결 정보의 소유자가 현재 계정 범위에 없으면 초안을 옮기지 않는다',async()=>{
 history.replaceState(null,'','/?auth=linked');
 sessionStorage.setItem('magi-account-link',JSON.stringify({owner:'other-guest',path:'/'}));
 sessionStorage.setItem('draft:other-guest','다른 초안');
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');
 expect(sessionStorage.getItem('draft:owner')).toBeNull();
 expect(sessionStorage.getItem('draft:other-guest')).toBe('다른 초안');
});
it('정지 등 403 오류는 새 익명 세션을 발급하지 않는다',async()=>{
 vi.mocked(api).mockImplementation(async path=>{if(path==='/api/auth/info')return {public:true,login_available:true};throw new ApiError('이 계정은 이용할 수 없습니다.',403);});
 render(<AuthProvider><Account/></AuthProvider>);
 expect(await screen.findByText('이 계정은 이용할 수 없습니다.')).toBeTruthy();
 expect(post).not.toHaveBeenCalled();
});
it('익명 세션 발급에 실패하면 오류와 재시도를 안내한다',async()=>{
 vi.mocked(post).mockRejectedValue(new ApiError('세션 발급 실패',503));
 vi.mocked(api).mockImplementation(async path=>{if(path==='/api/auth/info')return {public:true,login_available:true};throw new ApiError('로그인이 필요합니다.',401);});
 render(<AuthProvider><Account/></AuthProvider>);
 expect(await screen.findByText('세션 발급 실패')).toBeTruthy();
 expect(screen.getByRole('button',{name:'다시 시도'})).toBeTruthy();
});
it('인증 서버 오류는 로그인 화면에서 계속 안내한다',async()=>{
 vi.mocked(api).mockImplementation(async path=>{if(path==='/api/auth/info')return {public:true,login_available:true};throw new ApiError('서버 응답 오류',503);});
 render(<AuthProvider><Account/></AuthProvider>);
 expect(await screen.findByText('서버 응답 오류')).toBeTruthy();
});
it('StrictMode 재마운트에서도 인증과 상태 갱신을 유지하고 타이머를 해제한다',async()=>{
 const intervals=vi.spyOn(window,'setInterval'),cleared=vi.spyOn(window,'clearInterval');
 const view=render(<StrictMode><AuthProvider><Account/></AuthProvider></StrictMode>);
 await screen.findByText('owner');await screen.findByText('available');
 await waitFor(()=>expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status')).toHaveLength(1));
 expect(configureAuth).toHaveBeenCalledWith({publicMode:true,csrf:'fake-csrf'});
 const owned=intervals.mock.calls.map((call,index)=>({delay:call[1],id:intervals.mock.results[index].value})).filter(call=>call.delay===10000||call.delay===60000);
 expect(owned.map(call=>call.delay)).toEqual([10000,60000]);
 view.unmount();for(const call of owned)expect(cleared).toHaveBeenCalledWith(call.id);
});
it('인증 만료 시 계정 초안과 화면을 지우고 다른 계정의 초안은 보존한다',async()=>{
 let expired=false,created=false;
 vi.mocked(post).mockImplementation(async path=>{if(path==='/api/auth/guest')created=true;return {};});
 const original=vi.mocked(api).getMockImplementation()!;
 vi.mocked(api).mockImplementation(async (path,...args)=>{
   if(path==='/api/me' && expired) {if(!created) throw new ApiError('expired',401);return {id:'new-guest',role:'user',csrf:'new',identity_kind:'guest'};}
   return original(path,...args);
 });
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');
 sessionStorage.setItem('draft:owner','request');sessionStorage.setItem('draft:owner:job:question:v1','answer');sessionStorage.setItem('draft-backup:draft:owner','backup');sessionStorage.setItem('draft:other','other draft');
 expired=true;act(()=>window.dispatchEvent(new Event('signed-out')));
 expect(screen.queryByText('owner')).toBeNull();
 expect(await screen.findByText('new-guest')).toBeTruthy();
 expect(sessionStorage.getItem('draft:owner')).toBeNull();expect(sessionStorage.getItem('draft:owner:job:question:v1')).toBeNull();expect(sessionStorage.getItem('draft-backup:draft:owner')).toBeNull();expect(sessionStorage.getItem('draft:other')).toBe('other draft');
});
it('로그아웃은 기존 화면을 정리하고 새 익명 작업 공간을 연다',async()=>{
 let loggedOut=false,created=false;
 vi.mocked(post).mockImplementation(async path=>{if(path==='/api/logout') loggedOut=true;if(path==='/api/auth/guest')created=true;return {};});
 const original=vi.mocked(api).getMockImplementation()!;
 vi.mocked(api).mockImplementation(async(path,...args)=>{
   if(path==='/api/me' && loggedOut) {if(!created) throw new ApiError('expired',401);return {id:'new-guest',role:'user',csrf:'new',identity_kind:'guest'};}
   return original(path,...args);
 });
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');
 sessionStorage.setItem('draft:owner','로그아웃 전 초안');
 fireEvent.click(screen.getByRole('button',{name:'logout'}));
 await screen.findByText('new-guest');expect(screen.queryByText('owner')).toBeNull();expect(sessionStorage.getItem('draft:owner')).toBeNull();
});
it('로그아웃 요청이 실패하면 기존 세션을 유지한다',async()=>{
 vi.mocked(post).mockRejectedValue(new ApiError('로그아웃 실패',503));
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');
 fireEvent.click(screen.getByRole('button',{name:'logout'}));
 await waitFor(()=>expect(vi.mocked(post)).toHaveBeenCalledWith('/api/logout',{}));
 expect(screen.getByText('owner')).toBeTruthy();
});
it('실시간 연결 중에는 대체 조회를 멈추고 연결 해제 후 보이는 탭에서만 재개한다',async()=>{
 vi.useFakeTimers();
 let visible='visible';vi.spyOn(document,'visibilityState','get').mockImplementation(()=>visible as DocumentVisibilityState);
 await act(async()=>{render(<AuthProvider><Account/></AuthProvider>);});
 expect(screen.getByText('owner')).toBeTruthy();
 await act(async()=>{window.dispatchEvent(new CustomEvent('realtime-connection',{detail:{connected:true}}));});
 const calls=()=>vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status').length;
 const connectedCalls=calls();
 await act(async()=>{vi.advanceTimersByTime(20000);});expect(calls()).toBe(connectedCalls);
 await act(async()=>{window.dispatchEvent(new CustomEvent('realtime-connection',{detail:{connected:false}}));});
 const disconnectedCalls=calls();
 await act(async()=>{vi.advanceTimersByTime(10000);});expect(calls()).toBe(disconnectedCalls+1);
 visible='hidden';const hiddenCalls=calls();
 await act(async()=>{vi.advanceTimersByTime(20000);});expect(calls()).toBe(hiddenCalls);
});
it('이전 페이지 복원 시 정리한 상태 조회를 다시 시작한다',async()=>{
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');
 await waitFor(()=>expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status')).toHaveLength(1));
 act(()=>window.dispatchEvent(new Event('pagehide')));
 const restored=new Event('pageshow');Object.defineProperty(restored,'persisted',{value:true});
 act(()=>window.dispatchEvent(restored));
 await waitFor(()=>expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status')).toHaveLength(2));
});

it('실시간 상태보다 이전에 시작된 HTTP 응답이 현재 상태를 덮지 않는다',async()=>{
 let finish:(value:unknown)=>void=()=>{};
 const original=vi.mocked(api).getMockImplementation()!;
 vi.mocked(api).mockImplementation((path,...args)=>path==='/api/service/status'?new Promise(resolve=>{finish=resolve;}):original(path,...args));
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');await screen.findByText('loading');
 act(()=>{window.dispatchEvent(new CustomEvent('service-status',{detail:{ready:true,active_count:2,own_active_count:1}}));window.dispatchEvent(new CustomEvent('service-status',{detail:{ready:true,active_count:2,own_active_count:1}}));});
 expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status')).toHaveLength(1);
 await act(async()=>finish({ready:true,active_count:2,own_active_count:0}));
 await screen.findByText('busy');expect(screen.getByText('mine')).toBeTruthy();
 expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status')).toHaveLength(1);
 act(()=>window.dispatchEvent(new Event('pagehide')));
 await screen.findByText('loading');expect(screen.queryByText('mine')).toBeNull();
});
it('상태 조회 실패는 이전 사용 가능 상태를 지운다',async()=>{
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('ready');
 vi.mocked(api).mockRejectedValueOnce(new Error('offline'));
 act(()=>window.dispatchEvent(new Event('service-status')));
 await screen.findByText('error');
});
