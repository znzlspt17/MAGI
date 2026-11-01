import {useState} from 'react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import '@testing-library/jest-dom/vitest';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {PromptInput,ExpandableTextarea} from './PromptInput';
// jsdom에는 Radix Tooltip의 크기 관찰에 필요한 브라우저 API가 없다.
beforeEach(()=>vi.stubGlobal('ResizeObserver',class {
 observe(){}
 unobserve(){}
 disconnect(){}
}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
function Editor({send=()=>{}}:{send?:()=>void}){const [value,setValue]=useState('');return <PromptInput label="답변" buttonLabel="제출" value={value} onChange={e=>setValue(e.target.value)} onSend={send}/>;}
it('크게 쓰기 초안을 동기화하고 닫으면 포커스를 돌려준다',async()=>{
 const user=userEvent.setup(),send=vi.fn();render(<Editor send={send}/>);
 const input=screen.getByRole('textbox',{name:'답변'});
 await user.type(input,'작성 중');
 await user.click(screen.getByRole('button',{name:'답변 크게 쓰기'}));
 const expanded=screen.getByRole('textbox',{name:'답변 전체 편집'});
 expect(expanded).toHaveValue('작성 중');
 await user.clear(expanded);await user.type(expanded,'긴 답변\n다음 줄');
 await user.keyboard('{Control>}{Enter}{/Control}');expect(send).not.toHaveBeenCalled();
 await user.keyboard('{Escape}');
 expect(input).toHaveValue('긴 답변\n다음 줄');expect(input).toHaveFocus();
});
it('입력 높이를 여섯 줄에서 제한하고 내용을 지우면 다시 줄인다',()=>{
 render(<Editor/>);const input=screen.getByRole('textbox',{name:'답변'}) as HTMLTextAreaElement;
 input.style.lineHeight='27px';input.style.padding='0px';
 Object.defineProperty(input,'scrollHeight',{configurable:true,value:400});
 fireEvent.change(input,{target:{value:'여러 줄'}});expect(input.style.height).toBe('162px');expect(input.style.overflowY).toBe('auto');
 Object.defineProperty(input,'scrollHeight',{configurable:true,value:27});
 fireEvent.change(input,{target:{value:''}});expect(input.style.height).toBe('27px');expect(input.style.overflowY).toBe('hidden');
});
it('잠긴 질문 입력은 편집과 크게 쓰기를 막는다',()=>{
 render(<ExpandableTextarea label="답변" disabled/>);expect(screen.getByRole('textbox')).toBeDisabled();expect(screen.getByRole('button',{name:'답변 크게 쓰기'})).toBeDisabled();
});
