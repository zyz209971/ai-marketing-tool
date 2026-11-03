import {mkdir,copyFile,cp,writeFile,readFile} from 'node:fs/promises';
const env={};try{for(const line of (await readFile('.env','utf8')).split(/\r?\n/)){const match=line.match(/^([A-Z_]+)=(.*)$/);if(match)env[match[1]]=match[2].trim()}}catch{}
const mode=process.env.APP_API_MODE||env.APP_API_MODE||'mock',apiBaseUrl=process.env.APP_API_BASE_URL||env.APP_API_BASE_URL||'';
if(!['mock','real'].includes(mode))throw Error('APP_API_MODE 必须为 mock 或 real');
if(mode==='real'&&!/^https:\/\//.test(apiBaseUrl)&&!/^http:\/\/localhost(?::[0-9]+)?$/.test(apiBaseUrl))throw Error('真实模式需要 HTTPS 后端地址（本地开发允许 localhost）');
await mkdir('dist',{recursive:true});await copyFile('index.html','dist/index.html');await cp('src','dist/src',{recursive:true});await writeFile('dist/src/config.js','export const config = '+JSON.stringify({mode,apiBaseUrl})+';');await writeFile('dist/.nojekyll','');console.log('构建完成：dist，模式：'+mode);
