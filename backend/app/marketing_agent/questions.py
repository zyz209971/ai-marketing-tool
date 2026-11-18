"""Task-scoped batches: stable question IDs and revision-checked answer receipts."""
import hashlib
from uuid import uuid4
from fastapi import HTTPException
from .contracts import InputRequest, MessageInput

LABELS = {'sku_id':'主推哪款商品？','platform':'准备在哪个平台推广？',
 'promotion_pairs':'预计多少组同单两杯参加优惠？剩余杯数原价，不知道时可以先只看单位收益。',
 'start_date':'活动什么时候开始、持续到哪一天？','end_date':'活动最后一天是哪天？',
 'budget_minor':'营销预算上限是多少元？','spend_minor':'预计实际推广支出是多少元？',
 'scenario_qty':'按多少杯假设销量试算？也可以暂时只看单位收益。',
 'promotion_pairs':'预计多少组同单两杯会参加优惠？其余杯数按原价计算。',
 'variable_cost_override_minor':'单杯变动成本是多少元（食材与包材等）？',
 'min_contribution_override_minor':'平均每杯至少希望保留多少元贡献收益？','offer':'选择一个通过成本校验的优惠方案。'}
PREFIX = {'budget_minor':'预算','spend_minor':'预计花费','scenario_qty':'预计销量','promotion_pairs':'优惠组数',
 'variable_cost_override_minor':'单杯成本','min_contribution_override_minor':'最低贡献'}


def pending(state):
    fields = state.get('clarification_fields') or state.get('pending_fields') or []
    if not state.get('pending_fields') or state.get('stage') not in ('collecting','blocked'):
        return None
    attachment, labels = None, {}
    if state.get('active_attachment_id'):
        from .intake import active, missing
        attachment = active(state)
        if attachment:
            gaps = missing(attachment)
            fields = [g['path'] for g in gaps]
            labels = {g['path']:g['label'] for g in gaps}
    questions, used = [], set()
    for field in fields:
        if field in used:
            continue
        grouped = [field]
        if field=='start_date' and 'end_date' in fields:
            grouped.append('end_date')
        if attachment and field.startswith('products.') and not field.endswith('.name'):
            if '.'.join(field.split('.')[:2])+'.name' in fields:
                continue
        used.update(grouped)
        choices = []
        if not attachment:
            if field=='platform':
                choices=[{'id':k,'label':v,'patch':{'platform':k}} for k,v in [('xiaohongshu','小红书'),('douyin','抖音'),('wechat_official_account','微信公众号')]]
            elif field=='sku_id':
                from .business import catalog
                choices=[{'id':k,'label':p['name']+(' · '+p['spec'] if p.get('spec') else ''),'patch':{'sku_id':k}} for k,p in list(catalog(state['brief']).items())[:6]]
            elif field in ('scenario_qty','promotion_pairs'):
                choices=[{'id':'unit_only','label':'暂时只看单位收益','patch':{'roi_mode':'unit_only'}}]
            elif field=='min_contribution_override_minor' and state['brief'].get('task_kind')=='unit_economics':
                choices=[{'id':'numeric_only','label':'没有标准，先展示计算结果','patch':{'assess_minimum':False}}]
            elif field=='offer':
                choices=[{'id':str(i),'label':o['name'],'patch':{'offer':o['offer']}} for i,o in enumerate(state.get('options',[])) if o['evaluation']['result'].get('feasible') is True]
        label=labels.get(field,LABELS.get(field,state.get('reply','请补充这项信息。')))
        ident=hashlib.sha256((state['task_id']+str(state.get('active_attachment_id'))+field).encode()).hexdigest()[:16]
        reason='用于完善已上传资料；确认前不会成为品牌事实。' if attachment else '用于下一步安排或测算；未知信息不会当作零。'
        questions.append({'id':ident,'fields':grouped,'question':label,'reason':reason,'choices':choices,
                          'answer_prefix':labels.get(field,PREFIX.get(field,'')),'status':'pending'})
        if len(questions)==3:
            break
    if not questions:
        return None
    return InputRequest(id=uuid4().hex,task_id=state['task_id'],fields=[f for q in questions for f in q['fields']],
        question=state.get('reply',''),reason='可以一起回答，也可以先补已知的部分；选好后提交本组回答。',
        choices=questions[0]['choices'],attachment_id=state.get('active_attachment_id'),questions=questions).model_dump(mode='json')


def normalize_answer(request,batch):
    if not batch or request.question_id!=batch['id']:
        raise HTTPException(409,'这组问题已更新，请回答最新问题。')
    if request.answers and request.choice_id is not None:
        raise HTTPException(422,'不能混用单题选项与批次答案。')
    items={q['id']:q for q in batch.get('questions',[])}
    answers=request.answers
    if not answers and request.choice_id is not None:
        if request.text.strip():
            raise HTTPException(422,'请选择选项或填写回答。')
        first=next(iter(items),'')
        items=items or {'':{'choices':batch['choices'],'answer_prefix':''}}
        answers={first:{'choice_id':request.choice_id}}
    parts,patch=[],{}
    for ident,answer in answers.items():
        q=items.get(ident)
        if not q or not isinstance(answer,dict) or set(answer)-{'choice_id','text'}:
            raise HTTPException(422,'回答包含未知问题或字段。')
        value=answer.get('text','')
        if not isinstance(value,str) or len(value)>5000:
            raise HTTPException(422,'回答过长或格式不正确。')
        if answer.get('choice_id') is not None:
            if value.strip():
                raise HTTPException(422,'同一题不能同时选择和填写。')
            choice=next((c for c in q['choices'] if c['id']==answer['choice_id']),None)
            if choice is None:
                raise HTTPException(422,'选项不属于这道问题。')
            for key,v in choice['patch'].items():
                if key in patch and patch[key]!=v:
                    raise HTTPException(422,'选项互相冲突。')
                patch[key]=v
            parts.append(choice['label'])
        elif value.strip():
            prefix=q.get('answer_prefix','')
            parts.append((prefix+'：' if prefix else '')+value.strip())
    if request.text.strip():
        parts.append(request.text.strip())
    return MessageInput(request_id=request.request_id,expected_revision=request.expected_revision,text='\n'.join(parts),patch=patch)
