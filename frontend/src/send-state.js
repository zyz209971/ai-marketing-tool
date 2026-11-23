// Session storage is best effort: a quota/security error must never erase live input.
export function createSendState(storage, warn=()=>{}) {
  const memory=new Map();
  function read(key) {
    if(memory.has(key))return memory.get(key);
    try{return storage.getItem(key);}catch{warn();return null;}
  }
  function write(key,value) {
    memory.set(key,value);
    try{if(value===null)storage.removeItem(key);else storage.setItem(key,value);}catch{warn();}
  }
  return {
    read,write,
    draft:(id)=>read('compose:'+id)||'',
    saveDraft:(id,value)=>write('compose:'+id,value),
    attempt(id){try{return JSON.parse(read('agent-send:'+id)||'null');}catch{return null;}},
    saveAttempt(id,attempt){write('agent-send:'+id,JSON.stringify(attempt));},
    clearAttempt(id){write('agent-send:'+id,null);},
  };
}
export function prepareAttempt(action,payload,draft,answers={}) {
  return JSON.parse(JSON.stringify({action,payload,draft,answers,state:'prepared',runId:null}));
}
export function restoredDraft(current,attempt) {
  return current||attempt.draft||attempt.payload.text||'';
}
export function acceptedDraft(current,attempt) {
  const consumesInput=attempt.action==='answer'||attempt.action==='message'&&attempt.draft.trim()===(attempt.payload.text||'').trim();
  const restoredCommand=attempt.action==='message'&&!attempt.draft&&current===attempt.payload.text;
  return consumesInput&&current===attempt.draft||restoredCommand?'':current;
}
export function submissionPath(action) {
  return action==='confirm'?'confirm':action==='answer'?'answers':'messages';
}
