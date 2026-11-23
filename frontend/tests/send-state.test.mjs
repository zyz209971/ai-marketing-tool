import test from 'node:test';
import assert from 'node:assert/strict';
import {createSendState,prepareAttempt,restoredDraft,acceptedDraft,submissionPath} from '../src/send-state.js';
const storage=()=>{const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};};
test('reload retains immutable request, answer options and original revision for identical retry',()=>{
  const disk=storage(),s=createSendState(disk),answers={q1:{choice_id:'red'}};
  const a=prepareAttempt('answer',{request_id:'same-key',expected_revision:7,text:'原答案',answers},'原答案',answers);
  answers.q1.choice_id='changed';a.state='unknown';s.saveAttempt('a',a);
  const copy=createSendState(disk).attempt('a');
  assert.equal(copy.payload.expected_revision,7);assert.equal(copy.payload.request_id,'same-key');
  assert.equal(copy.payload.answers.q1.choice_id,'red');assert.equal(copy.answers.q1.choice_id,'red');
  assert.equal(submissionPath(copy.action),'answers');
});
test('failure restores empty composer without replacing newer input; acceptance only clears sent input',()=>{
  const a=prepareAttempt('message',{text:'旧内容'},'旧内容');
  assert.equal(restoredDraft('',a),'旧内容');assert.equal(restoredDraft('新内容',a),'新内容');
  assert.equal(acceptedDraft('旧内容',a),'');assert.equal(acceptedDraft('新内容',a),'新内容');
});
test('conversation drafts and attempts are isolated across navigation and reload',()=>{
  const disk=storage(),s=createSendState(disk);s.saveDraft('a','A');s.saveDraft('b','B');
  s.saveAttempt('a',prepareAttempt('message',{text:'A'},'A'));
  const reloaded=createSendState(disk);assert.equal(reloaded.draft('b'),'B');assert.equal(reloaded.attempt('b'),null);
  assert.equal(reloaded.attempt('a').draft,'A');
});
test('blocked storage preserves input and pending attempt in memory and warns',()=>{
  let warnings=0;const disk={getItem(){throw Error('blocked')},setItem(){throw Error('quota')},removeItem(){throw Error('blocked')}};
  const s=createSendState(disk,()=>warnings++);s.saveDraft('a','保留');
  s.saveAttempt('a',prepareAttempt('message',{text:'保留'},'保留'));
  assert.equal(s.draft('a'),'保留');assert.equal(s.attempt('a').draft,'保留');assert.ok(warnings);
});
test('quick command failure retains command even when composer was empty',()=>{
  const a=prepareAttempt('message',{text:'快速指令'},'');assert.equal(restoredDraft('',a),'快速指令');
  assert.equal(acceptedDraft('快速指令',a),'');
  const other=prepareAttempt('message',{text:'快速指令'},'未发送的文字');
  assert.equal(acceptedDraft('未发送的文字',other),'未发送的文字');
  assert.equal(acceptedDraft('未发送的文字',prepareAttempt('confirm',{},'未发送的文字')),'未发送的文字');
});
