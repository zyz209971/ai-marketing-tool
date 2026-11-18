"""Reviewable imports. Existing knowledge service remains the source of brand facts."""
import csv
import io
import json
from uuid import uuid4
from sqlalchemy import text
from fastapi import BackgroundTasks, File, UploadFile, HTTPException
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from .. import knowledge as kb, organization
from . import data, store, intake
from .contracts import AttachmentConfirm, MessageInput
from openai import APIError


def listing(task_id):
    store.get_task(task_id)
    with kb.engine.connect() as c:
        rows = c.execute(text('SELECT * FROM agent_attachments WHERE task_id=:id'), {'id': task_id}).mappings().all()
    return [intake.decorate({**dict(r), 'payload': json.loads(r['payload'])}) for r in rows]


async def prepare_knowledge(task_id, brand_id, file, bootstrap=False):
    background = BackgroundTasks()
    uploaded = await kb.upload(brand_id, background, file, user=kb.get_workspace())
    await background()
    preview = kb.version_preview(brand_id, uploaded['id'], uploaded['version_id'], kb.get_workspace())
    if preview['version']['status'] != 'pending_confirmation':
        raise ValueError('文件提取失败，请在品牌管理中检查后重试。')
    await run_in_threadpool(organization.analyze, brand_id, uploaded['version_id'], kb.get_workspace(), allow_partial=True)
    preview = kb.version_preview(brand_id, uploaded['id'], uploaded['version_id'], kb.get_workspace())
    snap = data.snapshot(brand_id)
    preview['structured_extraction'] = bool(preview['product_candidates'] or any(preview['brand_candidate'].values()))
    preview['brand_candidate'] = {**({} if bootstrap else {k:v for k,v in snap['brand'].items() if k in intake.BRAND_FIELDS}),
                                  **{k:v for k,v in preview['brand_candidate'].items() if v}}
    for product in preview['product_candidates']:
        from .facts import matching
        matches = matching([{'id':pid,**p} for pid,p in snap['products'].items()],product)
        product['ambiguous_spec']=len(matches)>1
        if len(matches)==1:
            product['id']=matches[0]['id']
            if not product.get('spec'): product['spec']=matches[0].get('spec','')
        if len(matches)==1:
            known = matches[0]
            if not product.get('price') and known['price'] is not None:
                product['price'] = f"{known['price']/100:g}元"
            if not product.get('selling'):
                product['selling'] = '；'.join(known['selling'])
    return {'document_id': uploaded['id'], 'version_id': uploaded['version_id'], 'preview': preview,
            'source_version': snap['version']}


def persist_draft(task_id, kind, payload):
    ident = uuid4().hex
    item = intake.decorate({'id': ident, 'kind': kind, 'status': 'pending', 'payload': payload})
    with kb.engine.begin() as c:
        c.execute(text("INSERT INTO agent_attachments(id,task_id,kind,status,payload) VALUES(:id,:task,:kind,'pending',:payload)"),
                  {'id':ident,'task':task_id,'kind':kind,'payload':json.dumps(payload,ensure_ascii=False)})
    return item


def draft_note(task_id, brand_id, message, bootstrap=False):
    import asyncio
    file = UploadFile(filename='对话补充资料.txt', file=io.BytesIO(message.encode('utf-8')))
    payload = asyncio.run(prepare_knowledge(task_id, brand_id, file,bootstrap=bootstrap))
    payload.update(filename='对话补充资料.txt', brand_id=brand_id)
    return persist_draft(task_id, 'knowledge', payload)


def brand_task(task_id):
    task = store.get_task(task_id)
    brand_id = task['state']['brief'].get('brand_id')
    if not brand_id:
        raise HTTPException(422, '请先选择实际品牌并新建对话；示例门店不接受真实资料。')
    if task['active_run']:
        raise HTTPException(409, '请等待当前任务完成后再上传或确认。')
    return task, brand_id


def register(router):
    @router.post('/conversations/{task_id}/attachments/{attachment_id}/save')
    def save_draft(task_id: str, attachment_id: str, req: AttachmentConfirm):
        task, brand_id = brand_task(task_id)
        item = next((a for a in listing(task_id) if a['id']==attachment_id and a['status']=='pending'), None)
        if not item or item['kind']!='knowledge' or not req.knowledge:
            raise HTTPException(422, '没有可编辑的品牌草稿。')
        import copy
        candidate = copy.deepcopy(item)
        preview = candidate['payload']['preview']
        edit = req.knowledge
        if set(edit)-{'brand','products','reviewed_text'}:
            raise HTTPException(422,'草稿包含未知字段。')
        if len(edit.get('products',preview['product_candidates']))!=len(preview['product_candidates']):
            raise HTTPException(422,'不能删除商品以绕过必填检查。')
        def checked(values, allowed):
            if not isinstance(values,dict) or set(values)-allowed or any(not isinstance(v,str) or len(v)>10000 for v in values.values()):
                raise HTTPException(422,'草稿字段或长度无效。')
            return values
        if 'brand' in edit:
            preview['brand_candidate'].update(checked(edit['brand'],set(intake.BRAND_FIELDS)))
        if 'products' in edit:
            for original,changed in zip(preview['product_candidates'],edit['products']):
                allowed=set(intake.PRODUCT_FIELDS)|{'id'}
                changed={k:v for k,v in changed.items() if k!='ambiguous_spec'}
                checked(changed,allowed)
                if changed.get('price') and data.price_minor(changed['price']) is None:
                    raise HTTPException(422,'请填写明确的商品单价。')
                original.update({k:v for k,v in changed.items() if k!='id'})
        if 'reviewed_text' in edit and (not isinstance(edit['reviewed_text'],str) or len(edit['reviewed_text'])>100000):
            raise HTTPException(422,'待入库正文无效。')
        if len(json.dumps(candidate,ensure_ascii=False))>250000:
            raise HTTPException(422,'资料过长。')
        if 'reviewed_text' in edit: preview['source_text']=edit['reviewed_text']
        before=intake.fields(item);after=intake.fields(candidate)
        candidate['payload'].setdefault('manual_edits',[]).append({'fields':[k for k,v in after.items() if before.get(k,{}).get('value')!=v['value']]})
        run_id,state=store.enqueue(task_id,MessageInput(request_id=uuid4().hex,expected_revision=req.expected_revision,text='保存资料草稿'), 'message')
        try:
            with kb.engine.begin() as c:
                c.execute(text("UPDATE agent_attachments SET payload=:payload WHERE id=:id AND status='pending'"), {'id':attachment_id,'payload':json.dumps(candidate['payload'],ensure_ascii=False)})
            state.update(intake.response(candidate))
            store.finish(run_id,task_id,state=state)
        except Exception:
            store.finish(run_id,task_id,error='草稿保存未完成，请刷新核对后重试。')
            raise
        return {'ok':True}

    @router.post('/conversations/{task_id}/attachments/{attachment_id}/cancel')
    def cancel(task_id: str, attachment_id: str, req: AttachmentConfirm):
        task, _ = brand_task(task_id)
        item = next((r for r in listing(task_id) if r['id']==attachment_id), None)
        if not item or item['status'] != 'pending':
            raise HTTPException(409, '资料已经处理或不存在。')
        run_id, state = store.enqueue(task_id, MessageInput(request_id=uuid4().hex, expected_revision=req.expected_revision,
                                                           text='暂不使用资料：'+item['payload']['filename']), 'message')
        try:
            with kb.engine.begin() as c:
                c.execute(text("UPDATE agent_attachments SET status='cancelled' WHERE id=:id"), {'id':attachment_id})
            state.update(active_attachment_id=None, intake_resume=None, pending_fields=[], stage='collecting',
                         reply='已保留原文件，但不会把这份草稿用于分析。可以上传修订资料，或继续告诉我你的需求。')
            store.finish(run_id, task_id, state=state)
        except Exception:
            store.finish(run_id, task_id, error='暂不使用资料失败，请刷新后重试。')
            raise
        return {'ok':True}

    @router.get('/conversations/{task_id}/business-template')
    def template(task_id: str):
        task, brand_id = brand_task(task_id)
        snap = data.snapshot(brand_id)
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(data.BusinessRow.model_fields))
        writer.writeheader()
        for pid in snap['products']:
            writer.writerow({'product_id': pid})
        return Response(content=output.getvalue().encode('utf-8-sig'), media_type='text/csv', headers={'Content-Disposition':'attachment; filename="business-template.csv"'})

    @router.post('/conversations/{task_id}/attachments', status_code=201)
    async def upload(task_id: str, kind: str, file: UploadFile = File(...)):
        task = store.get_task(task_id)
        brand_id = task['state']['brief'].get('brand_id')
        if kind not in ('business', 'knowledge'):
            raise HTTPException(422, '附件类型不支持。')
        if not brand_id and kind != 'knowledge':
            raise HTTPException(422, '请先上传品牌资料，再上传经营数据。')
        if intake.active(task['state']):
            raise HTTPException(409, '请先在对话中补齐并确认当前资料，再上传下一份文件。')
        filename = (file.filename or '').replace('\\','/').split('/')[-1]
        run_id, state = store.enqueue(task_id, MessageInput(request_id=uuid4().hex, expected_revision=task['revision'],
                                                          text='上传资料：'+filename), 'message')
        store.running(run_id)
        # Keep the activity request while intake occupies several chat turns.
        prior_text = task['state'].get('text', '')
        if prior_text.startswith(('上传资料：', '确认资料：', '暂不使用资料：')):
            prior_text = ''
        state['intake_resume'] = {'text': prior_text, 'patch': task['state'].get('input_patch', {})}
        try:
            bootstrap = not brand_id or state.get('brand_setup_pending', False)
            if not brand_id:
                brand = kb.create_brand(kb.BrandInput(name='待完善品牌', intro='上传资料待确认，尚未建立品牌事实。'), kb.get_workspace())
                brand_id = brand['id']
                state['brief'].update(brand_id=brand_id, sku_id=None, variable_cost_override_minor=None, min_contribution_override_minor=None)
                if state.get('strategy'):
                    state['strategies'].append({**state['strategy'],'status':'superseded'})
                state.update(strategy=None, tool_results={}, options=[], source_version='',
                             artifacts=[{**a,'stale':True} for a in state['artifacts']])
                # Retain only user intent, never the synthetic SKU or cost overrides.
                if state.get('intake_resume'):
                    state['intake_resume']['patch'] = {k:v for k,v in state['intake_resume'].get('patch',{}).items() if k not in ('sku_id','brand_id','variable_cost_override_minor','min_contribution_override_minor')}
                state['brand_setup_pending'] = True
            if kind == 'business':
                raw = await file.read(1024*1024+1)
                if len(raw) > 1024*1024:
                    raise ValueError('经营 CSV 最大 1MB。')
                payload = data.parse_csv(raw, brand_id, allow_partial=True)
            else:
                if not filename.lower().endswith(('.txt','.md','.csv','.pdf','.docx')):
                    raise ValueError('聊天资料整理支持 TXT、Markdown、CSV、PDF、DOCX；图片可在品牌管理中维护。')
                payload = await prepare_knowledge(task_id, brand_id, file, bootstrap=bootstrap)
            payload.update(filename=filename, brand_id=brand_id)
            item = persist_draft(task_id, kind, payload)
            state.update(intake.response(item))
            state.update(text='', input_patch={})
            store.finish(run_id, task_id, state=state)
            return item
        except APIError as exc:
            from .provider_errors import public_message
            message = public_message(exc)
            store.finish(run_id, task_id, state=state, error=message)
            raise HTTPException(502, message) from None
        except (ValueError, UnicodeError) as e:
            store.finish(run_id, task_id, state=state, error='资料提取失败，请检查文件后重新上传。')
            raise HTTPException(422, str(e)) from None
        except Exception:
            store.finish(run_id, task_id, state=state, error='资料提取失败，已有内容已保留，请重试。')
            raise

    @router.post('/conversations/{task_id}/attachments/{attachment_id}/confirm')
    def confirm(task_id: str, attachment_id: str, req: AttachmentConfirm):
        task, brand_id = brand_task(task_id)
        item = next((r for r in listing(task_id) if r['id']==attachment_id), None)
        if not item:
            raise HTTPException(404, '附件不存在。')
        if item['status']=='confirmed':
            return {'ok':True}
        payload = item['payload']
        if payload['brand_id'] != brand_id:
            raise HTTPException(409, '附件与会话品牌不一致。')
        if item['kind']=='knowledge' and data.snapshot(brand_id)['version'] != payload['source_version']:
            raise HTTPException(409, '品牌资料已变化，请重新上传整理，避免覆盖新内容。')
        try:
            knowledge = intake.confirmation(item, req.knowledge)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        if knowledge:
            from .facts import review
            import copy
            effective=copy.deepcopy(payload)
            effective['preview'].update(brand_candidate=knowledge.brand.model_dump() if knowledge.brand else {},product_candidates=[p.model_dump() for p in knowledge.products])
            before=intake.fields(item);after=intake.fields({**item,'payload':effective})
            edited=[k for k,v in after.items() if before.get(k,{}).get('value')!=v['value']]
            if edited:effective.setdefault('manual_edits',[]).append({'fields':edited})
            audit=review(effective)
            if set(c['id'] for c in audit['conflicts'])-set(req.accepted_conflicts):
                raise HTTPException(409,'新旧资料存在差异，请先保存编辑，查看差异并勾选接受后确认。')
            knowledge._agent_review={**effective,'task_id':task_id,'accepted_conflicts':req.accepted_conflicts}
        if knowledge and not payload['preview'].get('structured_extraction', True) and knowledge.reviewed_text is None:
            knowledge.reviewed_text = payload['preview']['source_text']
        elif knowledge and (knowledge.brand or knowledge.products) and knowledge.reviewed_text is None:
            # Keep the raw upload for audit, but retrieve only the reviewed facts.
            parts = []
            if knowledge.brand:
                parts += [f'{k}：{v}' for k, v in knowledge.brand.model_dump().items() if v]
            parts += [f'产品：{p.name}\n规格：{p.spec}\n价格：{p.price}\n卖点：{p.selling}' for p in knowledge.products]
            knowledge.reviewed_text = '\n'.join(parts)
        run_id, state = store.enqueue(task_id, MessageInput(request_id=uuid4().hex, expected_revision=req.expected_revision,
                                            text='确认资料：'+payload['filename']), 'message')
        store.running(run_id)
        try:
            if item['kind']=='business':
                data.save_business(brand_id, payload)
            else:
                kb.confirm_version(brand_id, payload['document_id'], payload['version_id'], knowledge, kb.get_workspace())
                state['brand_setup_pending'] = False
            with kb.engine.begin() as c:
                c.execute(text("UPDATE agent_attachments SET status='confirmed' WHERE id=:id"), {'id':attachment_id})
            if state.get('strategy'):
                state['strategies'].append({**state['strategy'],'status':'superseded'})
            state.update(strategy=None, tool_results={}, options=[], stage='collecting', pending_fields=[], active_attachment_id=None, text='', input_patch={},
                         artifacts=[{**a,'stale':True} for a in state['artifacts']],
                         reply='资料已确认并保存。后续分析会使用这一版本；已有活动需要重新测算、确认。你可以继续告诉我这次营销的目标。')
            resume = state.pop('intake_resume', None)
            if resume and resume.get('text'):
                from .runtime import invoke
                state.update(text=resume['text'], input_patch=resume.get('patch', {}), operation='message')
                try:
                    state = invoke(state)
                    state['reply'] = '资料已确认。接着处理你刚才的需求：\n'+state['reply']
                except Exception:
                    # The import succeeded; do not report a failed import or repeat writes.
                    state.update(stage='collecting', reply='资料已确认并保存，但继续分析未完成。请再发一次营销需求，资料无需重复上传。')
            store.finish(run_id, task_id, state=state)
        except ValueError as exc:
            store.finish(run_id, task_id, error='资料确认失败：'+str(exc))
            raise HTTPException(409, str(exc)) from None
        except Exception:
            store.finish(run_id, task_id, error='资料确认失败，请检查资料状态后重试。')
            raise
        return {'ok':True}
