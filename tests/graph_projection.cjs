// 표시 집계가 원본 관계와 버전 경계를 보존하는지 검증한다.
const assert = require('node:assert/strict');
const {build} = require('../frontend/static/knowledge-data.js');
const node = (id,kind,hash='v1',job='job') => ({id,kind,job_id:job,active:true,body:id,attrs:{artifact_hash:hash,artifact_path:'spec.md'}});
const nodes=[node('input','input'),node('a','spec'),node('b','spec'),node('c','spec','v2'),node('d','spec','v1','other-job'),node('orphan','decision')];
const edges=[['input','a'],['input','b'],['a','b'],['a','c'],['c','d']].map(([source,target],i)=>({id:'e'+i,source,target,kind:'derived'}));
const raw={nodes,edges,has_more:true};const before=JSON.stringify(raw);
const summary=build(raw);assert.equal(summary.nodes.length,4);assert.equal(summary.orphans.length,1);
assert.equal(summary.nodes.filter(n=>n.virtual).length,3);
assert.equal(summary.aliases.get('a'),summary.aliases.get('b'));
assert.notEqual(summary.aliases.get('a'),summary.aliases.get('c'));
assert.notEqual(summary.aliases.get('a'),summary.aliases.get('d'));
assert.equal(summary.edges.reduce((n,e)=>n+e.count,0)+summary.internalEdges,5);
const expanded=build(raw,{expanded:new Set([summary.aliases.get('a')])});assert.equal(expanded.aliases.get('a'),'a');assert.equal(expanded.aliases.get('b'),'b');
const detail=build(raw,{mode:'detail',showOrphans:true});assert.equal(detail.nodes.length,6);assert.equal(detail.edges.length,5);
assert.equal(JSON.stringify(raw),before);
const old={nodes:[node('x','spec',null),node('y','spec',null)],edges:[{id:'e',source:'x',target:'y',kind:'derived'}]};assert.equal(build(old).nodes.length,2);
console.log('projection boundaries passed');
