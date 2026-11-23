"""Bounded, evidence-only parsing for the explicitly selected offline demo."""
import re
from decimal import Decimal


class OfflineEditUnsupported(ValueError):
    pass


class UnchangedEdit(ValueError):
    pass

ALIASES = {'品牌名':'品牌名称','品牌简介':'品牌介绍','产品名':'产品名称','商品名称':'产品名称',
           '商品名':'产品名称','商品规格':'规格','产品规格':'规格','单杯售价':'价格',
           '可核实的商品卖点':'卖点','商品卖点':'卖点','商品分类':'分类'}
LABELS = ('品牌名称','品牌名','品牌介绍','品牌简介','品牌定位','表达风格','品牌偏好',
          '产品名称','产品名','商品名称','商品名','商品规格','产品规格','单杯售价',
          '可核实的商品卖点','商品卖点','商品分类','价格','卖点','分类','规格')
FIELD = re.compile(r'('+'|'.join(LABELS)+r')\s*[:：]\s*|(?P<tone>表达风格)\s*(?=自然|简洁|温柔|活泼|亲切|轻松|专业|简短)')


def explicit_fields(text):
    """Keep field order for multiple products; never include following instructions."""
    matches = list(FIELD.finditer(text))
    for i, match in enumerate(matches):
        label = match[1] or match['tone']
        value = text[match.end():matches[i+1].start() if i+1 < len(matches) else len(text)]
        value = re.split(r'[\n；;]', value, maxsplit=1)[0]
        value = re.split(r'[。！？]\s*(?:先|请|帮我|我想|不要|也不要|不生成|不创建|暂不)', value, maxsplit=1)[0]
        value = value.strip(' \t\r\n，,；;。')
        if value:
            yield ALIASES.get(label,label),value


def money_value(text):
    """Whole value only: do not turn a range, negative, or excess precision into money."""
    match=re.fullmatch(r'\s*(\d+(?:\.\d{1,2})?)\s*元?\s*[。！]?\s*',text)
    if not match:return None
    amount=int(Decimal(match[1])*100)
    return amount if amount<=100000 else None


def cost_value(text,pending=False):
    matches=list(re.finditer(r'(?:单杯|每杯)(?:变动)?成本\s*(?:[:：]|是|为)?\s*([^，,；;。\n]+(?:\.\d+)?)[。]?',text))
    if matches:
        # A conflicting second value must not silently win.
        values=[money_value(m[1]) for m in matches]
        return values[0] if all(v==values[0] for v in values) else None
    return money_value(text) if pending else None


def unit_request(text):
    return bool(re.search(r'只(?:检查|判断|测算).*?(?:优惠|成本|半价)|只检查第二杯|只看单位收益|先只展示计算结果|单位(?:收益|优惠|测算)|只(?:展示|计算|测算|看).*?(?:两杯|收入|贡献收益)',text))


def specified_title(text):
    match=re.search(r'标题\s*(?:改成|改为|换成|替换为|设为|改\s*[:：])\s*(.*)',text,re.S)
    if not match:return None
    rest=match[1].strip().lstrip(':：').strip()
    if rest[:1] in ('“','‘','"',"'"):
        end={'“':'”','‘':'’','"':'"',"'":"'"}[rest[0]]
        return rest[1:rest.find(end,1)].strip() if end in rest[1:] else None
    return re.split(r'[\n；;。]|[，,]\s*(?:正文|不新增|不添加|其他)',rest,maxsplit=1)[0].strip() or None


def title_edit(text):
    return bool(re.search(r'标题.*(?:改|换|活泼|简短|温柔|简洁)|(?:改|换).*标题',text))


def reusable_style(text):
    # A literal title can contain tone words, but remains an instruction for this edit.
    if specified_title(text) is not None:return None
    match=re.search(r'(?:语气|风格|标题)\s*(?:改得|改成|改为|要|用|更)?\s*[，,:：]?\s*((?:(?:自然|简洁|温柔|活泼|亲切|轻松|专业|简短|一点|点|、|，|,|又|更|且|和)\s*)+)',text)
    if match:
        tones=re.findall(r'自然|简洁|温柔|活泼|亲切|轻松|专业|简短',match[1])
        if tones and text[:match.start()].strip() in ('','这次','本次') and not text[match.end():].strip(' 。！') and not title_edit(text):
            return text.strip(' 。！')
        return '、'.join(dict.fromkeys(tones)) or None
    return None
