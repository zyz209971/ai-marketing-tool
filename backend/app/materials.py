"""Private durable artwork, product-photo layouts and export bundles."""
import io
import json
import html
import os
import time
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy import text
from . import knowledge as kb

router = APIRouter(prefix='/api/knowledge')


def store(brand, raw):
    with Image.open(io.BytesIO(raw)) as source:
        if source.width * source.height > 25000000:
            raise ValueError('图片尺寸过大')
        output = io.BytesIO()
        ImageOps.exif_transpose(source).convert('RGB').save(output, 'PNG')
    aid, key = kb.ident(), kb.ident()
    target = kb.STORAGE / key
    target.write_bytes(output.getvalue())
    try:
        with kb.engine.begin() as c:
            c.execute(text("INSERT INTO kb_assets(id,brand_id,storage_key,mime,created) VALUES(:id,:brand,:key,'image/png',:now)"), {'id': aid, 'brand': brand, 'key': key, 'now': time.time_ns()})
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return {'asset_id': aid, 'url': f'/api/knowledge/brands/{brand}/assets/{aid}'}


@router.get('/brands/{brand_id}/assets/{asset_id}')
def asset(brand_id: str, asset_id: str, user: str = Depends(kb.get_workspace)):
    with kb.engine.connect() as c:
        kb.owned(c, brand_id, user)
        row = c.execute(text('SELECT storage_key FROM kb_assets WHERE id=:id AND brand_id=:brand'), {'id': asset_id, 'brand': brand_id}).first()
    if not row:
        raise HTTPException(404, '素材不存在。')
    return FileResponse(kb.STORAGE / row[0], media_type='image/png', headers={'Cache-Control': 'private, no-store'})


def font(size):
    paths = [os.getenv('BRAND_FONT_PATH', ''), 'C:/Windows/Fonts/msyh.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    for path in paths:
        if path and Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise ValueError('请配置 BRAND_FONT_PATH 为支持中文的字体文件。')


def lines(value, width=22, maximum=4):
    parts = []
    for paragraph in str(value).splitlines():
        parts.extend(paragraph[i:i+width] for i in range(0, len(paragraph), width))
    return '\n'.join(parts[:maximum])


def photo_gallery(brand_id, user, content, product_ids, count=3):
    photos = []
    with kb.engine.connect() as c:
        brand = kb.owned(c, brand_id, user)
        for pid in product_ids:
            row = c.execute(text('SELECT p.*,v.storage_key FROM kb_products p LEFT JOIN kb_documents d ON d.id=p.image_document_id LEFT JOIN kb_versions v ON v.id=d.active_version WHERE p.id=:id AND p.brand_id=:brand AND p.archived=0'), {'id': pid, 'brand': brand_id}).mappings().first()
            if not row:
                raise ValueError('产品已归档或不属于该品牌，请重新选择。')
            if row['storage_key']:
                photos.append(dict(row))
    if not photos:
        raise ValueError('请先为所选产品上传实拍图，或选择 AI 创意配图。')
    cover = content['platform'] == 'wechat_official_account'
    width, height = (1200, 510) if cover else (1080, 1440)
    outputs = []
    for page in range(1 if cover else count):
        canvas = Image.new('RGB', (width, height), '#f7f0e6')
        draw = ImageDraw.Draw(canvas)
        draw.text((55, 30), brand['name'][:30], font=font(28), fill='#805238')
        title = content['title'] if page == 0 else photos[(page-1) % len(photos)]['name']
        draw.multiline_text((55, 80), lines(title, 28 if cover else 18, 2), font=font(46), fill='#342b25', spacing=12)
        top, bottom = (205, 425) if cover else (300, 1120)
        selected = photos if page == 0 else [photos[(page-1) % len(photos)]]
        cell_width = (width-110)//len(selected)
        for i, product in enumerate(selected):
            with Image.open(kb.STORAGE / product['storage_key']) as source:
                if source.width*source.height > 25000000:
                    raise ValueError('产品图片尺寸过大，请缩小后重新上传。')
                photo = ImageOps.contain(ImageOps.exif_transpose(source).convert('RGB'), (cell_width-15, bottom-top))
            canvas.paste(photo, (55+i*cell_width+(cell_width-photo.width)//2, top+(bottom-top-photo.height)//2))
        caption = ' / '.join(p['name'] + (' · '+p['price'] if p['price'] else '') for p in selected)
        draw.multiline_text((55, bottom+20), lines(caption, 40 if cover else 24, 2), font=font(26 if cover else 36), fill='#805238', spacing=10)
        if not cover:
            detail = content.get('summary') if page == 0 else selected[0]['selling']
            draw.multiline_text((55, 1260), lines(detail or '', 32, 3), font=font(26), fill='#60554a', spacing=10)
            draw.text((width-100, height-50), f'{page+1}/{count}', font=font(22), fill='#805238')
        raw = io.BytesIO()
        canvas.save(raw, 'PNG')
        outputs.append(store(brand_id, raw.getvalue()))
    return {'gallery': outputs, 'image': outputs[0], 'mock': False, 'method': 'product_photo', 'final_prompt': '使用产品原图排版，标题和价格来自已确认资料。'}


@router.get('/brands/{brand_id}/works/{work_id}/export')
def export(brand_id: str, work_id: str, user: str = Depends(kb.get_workspace)):
    with kb.engine.connect() as c:
        kb.owned(c, brand_id, user)
        row = c.execute(text('SELECT payload FROM kb_works WHERE id=:id AND brand_id=:brand'), {'id': work_id, 'brand': brand_id}).first()
        if not row:
            raise HTTPException(404, '请先保存作品。')
        work = json.loads(row[0])
        result = work['result']
        files = []
        for index, image in enumerate(result.get('gallery', [])):
            aid = image.get('asset_id')
            asset_row = c.execute(text('SELECT storage_key FROM kb_assets WHERE id=:id AND brand_id=:brand'), {'id': aid, 'brand': brand_id}).first()
            if not asset_row:
                raise HTTPException(409, '作品素材缺失，请重新生成后保存。')
            files.append((f'images/{index+1:02d}.png', (kb.STORAGE / asset_row[0]).read_bytes()))
    esc = html.escape
    title, body = result.get('title', ''), result.get('body', '')
    paragraphs = ''.join('<p style="line-height:1.9;margin:18px 0">'+esc(p).replace('\n', '<br>')+'</p>' for p in body.split('\n\n'))
    images = ''.join(f'<img alt="营销配图" style="width:100%;height:auto" src="{name}">' for name, _ in files)
    article = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+esc(title)+'</title><body><article style="max-width:720px;margin:32px auto;padding:20px;font-family:sans-serif"><h1>'+esc(title)+'</h1>'+images+'<p>'+esc(result.get('summary', ''))+'</p>'+paragraphs+'</article></body></html>'
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('文案.txt', '\n\n'.join([title, result.get('summary', ''), body, result.get('tags', '')]))
        archive.writestr('文章.html', article)
        archive.writestr('作品.json', json.dumps(work, ensure_ascii=False, indent=2))
        archive.writestr('使用说明.txt', '图片按编号排列。文章.html 可预览公众号排版；发布前请核对文案和活动信息。\n'+('本作品没有持久化配图。' if not files else ''))
        for name, raw in files:
            archive.writestr(name, raw)
    return Response(output.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="marketing-materials.zip"'})
