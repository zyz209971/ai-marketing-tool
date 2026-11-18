"""Export the same contracts used at runtime, without importing application databases."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'backend'))
from app.marketing_agent.contracts import (Brief, MessageInput, ConfirmInput, ToolResult, CreateConversation, AttachmentConfirm,
                                          SalesRequest, ConstraintsRequest, EvaluationRequest, RESULT_TYPES, InputRequest, AnswerInput)
from app.marketing_agent import business

output = {'schema_version': '1.0', 'scope': 'brand-scoped-single-store-pickup; synthetic or user-provided',
          'units': {'money': 'integer CNY cents', 'discount': 'pay basis points 0..10000',
                    'period': '[start_date,end_date)', 'timezone': 'Asia/Shanghai'},
          'InputRequest': InputRequest.model_json_schema(), 'AnswerInput': AnswerInput.model_json_schema(),
          'CreateConversation': CreateConversation.model_json_schema(), 'AttachmentConfirm': AttachmentConfirm.model_json_schema(),
          'Brief': Brief.model_json_schema(), 'MessageInput': MessageInput.model_json_schema(),
          'ConfirmInput': ConfirmInput.model_json_schema(), 'ToolResult': ToolResult.model_json_schema(),
          'requests': {name: cls.model_json_schema() for name, cls in
                       [('get_sales_summary', SalesRequest), ('get_business_constraints', ConstraintsRequest), ('evaluate_promotion', EvaluationRequest)]},
          'results': {name: cls.model_json_schema() for name, cls in RESULT_TYPES.items()}}
(ROOT/'docs').mkdir(exist_ok=True)
(ROOT/'docs'/'agent-contracts.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
print('Exported docs/agent-contracts.json')

base = {'sku_id': 'T001', 'platform': 'xiaohongshu', 'start_date': '2026-11-16', 'end_date': '2026-11-23',
        'budget_minor': 20000, 'spend_minor': 20000, 'scenario_qty': 160,'promotion_pairs':20,
        'offer': {'type': 'second_cup_discount', 'pay_bps': 5000}}
examples = []
for name, change in [('negative_roi', {}), ('missing_quantity', {'scenario_qty': None}),
                     ('infeasible_cost', {'variable_cost_override_minor': 1000}), ('zero_spend', {'spend_minor': 0})]:
    request = EvaluationRequest(brief=Brief(**{**base, **change}))
    examples.append({'case': name, 'request': request.model_dump(mode='json'),
                     'response': business.evaluate_promotion(request)})
(ROOT/'docs'/'agent-tool-examples.json').write_text(json.dumps(examples, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
print('Exported docs/agent-tool-examples.json')
