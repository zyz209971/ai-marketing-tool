"""Task-dependent requirements. Models interpret; server owns execution gates."""
NAMES={'brand_setup':'建立品牌资料','content':'普通文案','unit_economics':'优惠可行性','campaign':'活动策略'}


def missing(brief):
    kind=brief.get('task_kind','campaign')
    if kind=='brand_setup':return []
    if kind=='content':
        fields=['platform']+(['sku_id'] if brief.get('content_scope','product')=='product' else [])
    elif kind=='unit_economics':fields=['sku_id','offer']
    else:
        fields=['sku_id','platform','start_date','end_date','budget_minor']
        if brief.get('roi_mode','scenario')=='scenario':
            fields+=['spend_minor','scenario_qty']
            if (brief.get('offer') or {}).get('type')=='second_cup_discount':fields+=['promotion_pairs']
    return [key for key in fields if brief.get(key) is None]


def onboarding(state):
    return {'stage':'collecting','reply':'我会先帮你建立品牌资料。请上传现有的品牌介绍、菜单或商品说明，已有多少就先提供多少；也可以直接说“品牌名称：…；品牌介绍：…”。我会整理成草稿，一次询问必要的缺项，核对确认后入库，再继续你刚才的需求。',
            'pending_fields':[],'clarification_fields':[],'suggestions':['我先上传品牌介绍和菜单','我想先建立品牌资料'],
            'tool_results':{},'next_node':'wait'}
