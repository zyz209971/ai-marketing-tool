import test from 'node:test';
import assert from 'node:assert/strict';
import {parseRoute,routeHref} from '../src/router.js';
test('default view is chat and task links retain task identifiers',()=>{
 assert.deepEqual(parseRoute(''),{view:'chat',taskId:null});
 assert.deepEqual(parseRoute('#/chat/abc_123'),{view:'chat',taskId:'abc_123'});
 assert.equal(routeHref('chat','abc_123'),'#/chat/abc_123');
});
test('unknown routes fall back safely and management routes have no task',()=>{
 assert.deepEqual(parseRoute('#/products'),{view:'products',taskId:null});
 assert.deepEqual(parseRoute('#/conversations'),{view:'conversations',taskId:null});
 assert.equal(parseRoute('#/invalid').view,'chat');
 assert.equal(parseRoute('#/chat/%3Cscript%3E').taskId,null);
});
