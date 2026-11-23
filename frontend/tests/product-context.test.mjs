import test from 'node:test';
import assert from 'node:assert/strict';
import {productContext} from '../src/product-context.js';
const p={id:'sku1',brand:'brand1',name:'桂花乌龙',spec:'500mL'};
test('zero selection stays generic; one selection carries identity and editable prompt',()=>{
  assert.deepEqual(productContext([], [p], 'brand1'),{brandId:'brand1'});
  const result=productContext(['sku1'],[p],'brand1');
  assert.equal(result.skuId,'sku1');assert.match(result.text,/桂花乌龙（500mL）/);
});
test('multiple, missing, archived and different brand products never silently fall back',()=>{
  for(const [ids,rows] of [[['sku1','sku2'],[p]],[['absent'],[p]],[['sku1'],[{...p,archived:true}]],[['sku1'],[{...p,brand:'other'}]]])
    assert.throws(()=>productContext(ids,rows,'brand1'));
});
