import {StrictMode} from 'react';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {AuthProvider,useAuth} from './Auth';
import {api,configureAuth} from './api';
vi.mock('./api',()=>({api:vi.fn(),post:vi.fn().mockResolvedValue({}),configureAuth:vi.fn(),clearRequests:vi.fn()}));
function Account(){const auth=useAuth();return <><p>{auth.user?.id}</p><p>{auth.status.busy?'busy':'available'}</p><p>{auth.status.checkState}</p><p>{auth.status.mine?'mine':'not-mine'}</p><button onClick={()=>void auth.logout()}>logout</button></>;}
beforeEach(()=>{vi.mocked(api).mockImplementation(async(path:string)=>path==='/api/auth/info'?{public:true,login_available:true}:path==='/api/me'?{id:'owner',role:'user',csrf:'fake-csrf'}:path==='/api/service/status'?{busy:false}:{runs:1,remaining_runs:3});sessionStorage.clear();});
afterEach(()=>{cleanup();vi.useRealTimers();vi.clearAllMocks();vi.restoreAllMocks();});
it('StrictMode 재마운트에서도 인증과 상태 갱신을 유지하고 타이머를 해제한다',async()=>{
 const intervals=vi.spyOn(window,'setInterval'),cleared=vi.spyOn(window,'clearInterval');
 const view=render(<StrictMode><AuthProvider><Account/></AuthProvider></StrictMode>);
 await screen.findByText('owner');await screen.findByText('available');
 await waitFor(()=>expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status')).toHaveLength(1));
 expect(configureAuth).toHaveBeenCalledWith({publicMode:true,csrf:'fake-csrf'});
 const owned=intervals.mock.calls.map((call,index)=>({delay:call[1],id:intervals.mock.results[index].value})).filter(call=>call.delay===2000||call.delay===30000);
 expect(owned.map(call=>call.delay)).toEqual([2000,30000]);
 view.unmount();for(const call of owned)expect(cleared).toHaveBeenCalledWith(call.id);
});
it('인증 만료 시 계정 초안과 화면을 지우고 다른 계정의 초안은 보존한다',async()=>{
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');
 sessionStorage.setItem('draft:owner','request');sessionStorage.setItem('draft:owner:job:question:v1','answer');sessionStorage.setItem('draft:other','other draft');
 act(()=>window.dispatchEvent(new Event('signed-out')));
 expect(screen.queryByText('owner')).toBeNull();expect(sessionStorage.getItem('draft:owner')).toBeNull();expect(sessionStorage.getItem('draft:owner:job:question:v1')).toBeNull();expect(sessionStorage.getItem('draft:other')).toBe('other draft');
 expect(screen.getByRole('link',{name:'Google로 로그인'})).toBeTruthy();
});
it('로그아웃은 화면과 인증을 정리한다',async()=>{
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');
 fireEvent.click(screen.getByRole('button',{name:'logout'}));
 await screen.findByRole('link',{name:'Google로 로그인'});expect(screen.queryByText('owner')).toBeNull();
});
it('이전 페이지 복원 시 정리한 상태 조회를 다시 시작한다',async()=>{
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');
 await waitFor(()=>expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status')).toHaveLength(1));
 act(()=>window.dispatchEvent(new Event('pagehide')));
 const restored=new Event('pageshow');Object.defineProperty(restored,'persisted',{value:true});
 act(()=>window.dispatchEvent(restored));
 await waitFor(()=>expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status')).toHaveLength(2));
});

it('WebSocket 소유 주장 대신 HTTP 재조회 결과를 사용하고 중복 신호를 합친다',async()=>{
 let finish:(value:unknown)=>void=()=>{};
 const original=vi.mocked(api).getMockImplementation()!;
 vi.mocked(api).mockImplementation((path,...args)=>path==='/api/service/status'?new Promise(resolve=>{finish=resolve;}):original(path,...args));
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('owner');await screen.findByText('loading');
 act(()=>{window.dispatchEvent(new CustomEvent('service-status',{detail:{busy:true,mine:true}}));window.dispatchEvent(new CustomEvent('service-status',{detail:{busy:true,mine:true}}));});
 expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status')).toHaveLength(1);
 await act(async()=>finish({busy:true,mine:false,phase:'running'}));
 await screen.findByText('busy');expect(screen.queryByText('mine')).toBeNull();
 expect(vi.mocked(api).mock.calls.filter(([path])=>path==='/api/service/status')).toHaveLength(2);
 act(()=>window.dispatchEvent(new Event('pagehide')));
 await act(async()=>finish({busy:true,mine:true}));
 await screen.findByText('loading');expect(screen.queryByText('mine')).toBeNull();
});
it('상태 조회 실패는 이전 사용 가능 상태를 지운다',async()=>{
 render(<AuthProvider><Account/></AuthProvider>);await screen.findByText('ready');
 vi.mocked(api).mockRejectedValueOnce(new Error('offline'));
 act(()=>window.dispatchEvent(new Event('service-status')));
 await screen.findByText('error');
});
