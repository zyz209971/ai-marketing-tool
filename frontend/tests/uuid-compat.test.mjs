import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {runInNewContext} from 'node:vm';

// Execute the production ID factories with the browser capability absent on HTTP.
for (const [file,name] of [['agent.js','key'],['app.js','uid'],['services/api.js','uid']]) {
  const source=await readFile(new URL('../src/'+file,import.meta.url),'utf8');
  const declaration=source.split(/\r?\n/).find(line=>new RegExp('^const '+name+'\\s*=').test(line));
  test(file+' generates usable IDs without crypto or randomUUID',()=>{
    assert.ok(declaration);
    for(const crypto of [undefined,{}]) {
      const ids=runInNewContext(declaration+`; Array.from({length:50},()=>${name}());`,{crypto});
      assert.equal(new Set(ids).size,50);
      assert.ok(ids.every(id=>typeof id==='string'&&id.length>=8&&id.length<=100));
    }
  });
  test(file+' uses native UUID when available',()=>{
    assert.equal(runInNewContext(declaration+`; ${name}();`,{crypto:{randomUUID:()=> 'native-test-uuid'}}),'native-test-uuid');
  });
}
