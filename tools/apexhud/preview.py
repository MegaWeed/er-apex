"""Draw pack recommendations with original UIIA PNGs and local bitmap glyphs."""
from pathlib import Path
import math
import json
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont
import numpy as np


class Renderer:
    def __init__(self, root, pack, size=(1920, 1080), background=True):
        self.root, self.pack = root, pack
        self.canvas = Image.new('RGBA', size, (38, 43, 49, 255) if background else (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.canvas)
        self.fonts = json.loads((root / pack['font_catalog']).read_text(encoding='utf8'))['fonts']
        self.profile = next(p for f in self.fonts if f['guid'] == pack['font_choice']['guid']
            for p in f['profiles'] if p['font_index'] == pack['font_choice']['font_index'])
        self.white = tuple(self.color('DEFAULT'))
        self.dark = (0, 0, 0, 190)

    def color(self, key, alpha=255):
        row = json.loads((self.root / self.pack['palette']).read_text(encoding='utf8'))['colors'][key]
        return tuple(row['variants']['default']) + (alpha,)

    @lru_cache(None)
    def glyph(self, cp, profile_index=None):
        profile = self.profile
        if profile_index is not None:
            profile = next(p for f in self.fonts for p in f['profiles'] if p['font_index'] == profile_index)
        g = profile['glyphs'].get(str(cp))
        if g is None:
            if profile_index is not None:
                return None
            g = next((p['glyphs'][str(cp)] for f in self.fonts for p in f['profiles'] if str(cp) in p['glyphs']), None)
        if g is None:
            return None
        im = Image.open(self.root / g['image']).convert('RGBA')
        raw = np.asarray(im.getchannel('A')).astype(np.float32)
        # Readable schematic only: shader threshold/softness were not recovered.
        a = Image.fromarray(np.clip((raw - 176) * (255 / 16), 0, 255).astype(np.uint8))
        bounds = a.getbbox()
        if bounds is None:
            return None
        return a.crop(bounds)

    def text(self, x, y, text, height=24, fill=None, profile_index=None, align='left'):
        fill = fill or self.white
        reference = self.glyph(ord('0'), profile_index)
        reference_height = reference.height if reference else 40
        scale = height / reference_height
        glyphs = []
        for c in text:
            if c == ' ':
                glyphs.append((None, round(height * .4)))
                continue
            a = self.glyph(ord(c), profile_index)
            if a is None:
                # Missing glyph is explicit in verification, not a fabricated font.
                glyphs.append((None, round(height * .55)))
                continue
            a = a.resize((max(1, round(a.width * scale)), max(1, round(a.height * scale))), Image.Resampling.LANCZOS)
            glyphs.append((a, a.width + max(1, round(height * .08))))
        width = sum(w for _, w in glyphs)
        if align == 'right':
            x -= width
        elif align == 'center':
            x -= width / 2
        for a, advance in glyphs:
            if a is not None:
                letter = Image.new('RGBA', a.size, fill)
                letter.putalpha(a.point(lambda v: round(v * fill[3] / 255)))
                self.canvas.alpha_composite(letter, (round(x), round(y + max(0, height-a.height))))
            x += advance
        return width

    def image(self, image, rect, tint=None):
        x, y, w, h = rect
        im = Image.open(self.root / image).convert('RGBA')
        s = min(w/im.width, h/im.height)
        im = im.resize((max(1, round(im.width*s)), max(1, round(im.height*s))), Image.Resampling.LANCZOS)
        if tint:
            pixels = np.asarray(im).copy()
            pixels[..., :3] = (pixels[..., :3].astype(float) * np.array(tint[:3]) / 255).astype(np.uint8)
            im = Image.fromarray(pixels)
        self.canvas.alpha_composite(im, (round(x+(w-im.width)/2), round(y+(h-im.height)/2)))

    def panel(self, rect, stroke=None):
        x, y, w, h = rect
        points = [(x+17, y), (x+w, y), (x+w-17, y+h), (x, y+h)]
        self.draw.polygon(points, fill=self.dark)
        if stroke:
            self.draw.line(points+[points[0]], fill=stroke, width=2)

    def line(self, a, b, fill, thickness=2):
        # the pack's widths can be fractional (crosshair 2.4 px); PIL takes whole pixels
        thickness = max(1, round(thickness))
        self.draw.line([a, b], fill=(0, 0, 0, fill[3]), width=thickness+2)
        self.draw.line([a, b], fill=fill, width=thickness)

    def full_hud(self, state='hip', shield_demo=True):
        elements = {e['id']: e for e in self.pack['elements']}
        sample = self.pack['preview_state']
        weapon = elements['weapon_slot']
        x, y, w, h = weapon['layout']['bounds_px']
        self.panel([x, y, w, h], self.color('FRAME_LOOT_TIER1'))
        icon = next(r for r in weapon['rendering'] if 'image' in r)
        self.image(icon['payload_image'], [x+140, y+6, 174, 49])
        loc = json.loads((self.root / self.pack['localization']).read_text(encoding='utf8'))
        name = loc[weapon['localization_key']]['values'].get(self.pack['default_language'], loc[weapon['localization_key']]['values']['english'])
        # Long localized names sit above the panel rather than over the gun icon.
        self.text(x+22, y-33, name, 24)
        self.text(x+22, y+53, str(sample['magazine']), 42,profile_index=self.pack['font_choice']['numeric_font_index'])
        self.text(x+104, y+65, '/ --', 24, self.color('HUD_LOOT_TIER1'))
        self.draw.line([(x+210,y+88),(x+323,y+88)], fill=self.color('HUD_LOOT_TIER1'), width=2)
        if state == 'reload':
            self.draw.rectangle([x+18,y+104,x+326,y+107],fill=self.dark)
            self.draw.rectangle([x+18,y+104,x+172,y+107],fill=self.white)
        health = elements['health']
        hx, hy, hw, hh = health['layout']['bounds_px']
        self.panel([hx,hy,hw,hh],self.color('FRAME_LOOT_TIER1'))
        portrait = next(r for r in health['rendering'] if 'image' in r)
        self.image(portrait['payload_image'], [hx,hy,94,94])
        self.text(hx+112,hy+3,sample['player_name'],21)
        legend_key = health.get('localization_key', '#character_fuse_NAME')
        legend = loc[legend_key]['values'].get(self.pack['default_language'],loc[legend_key]['values']['english'])
        self.text(hx+112,hy+32,legend,18,self.color('HUD_LOOT_TIER1'))
        self.draw.rectangle([hx+112,hy+79,hx+375,hy+93],fill=self.dark)
        self.draw.rectangle([hx+112,hy+79,hx+112+263*(sample['hp']/sample['max_hp']),hy+93],fill=self.white)
        self.text(hx+112,hy+97,f"{sample['hp']} / {sample['max_hp']}",15)
        if shield_demo:
            sx,sy,sw,sh=elements['shield']['layout']['bounds_px']
            col=self.color(f"HUD_LOOT_TIER{sample['shield_level']}")
            seg=sample['segment_count']; gap=4; width=(sw-gap*(seg-1))/seg
            for i in range(seg):
                x1=sx+i*(width+gap)
                self.draw.rectangle([x1,sy,x1+width,sy+sh],fill=self.dark,outline=col,width=1)
                fraction=max(0,min(1,sample['shield_hp']/sample['shield_max']*seg-i))
                self.draw.rectangle([x1+2,sy+2,x1+2+(width-4)*fraction,sy+sh-2],fill=col)
        bx,by,bw,bh=elements['boss_health']['layout']['bounds_px']
        self.text(bx,by,sample['boss_name'],23)
        self.draw.rectangle([bx,by+31,bx+bw,by+45],fill=self.dark,outline=self.color('HUD_LOOT_TIER1'))
        self.draw.rectangle([bx+2,by+33,bx+sample['boss_fraction']*bw,by+43],fill=self.color('HUD_DAMAGE_TEXT_BLEED'))
        self.text(bx+bw,by,'68%',20,align='right')
        cx,cy=elements['crosshair']['layout']['anchor_position_px']
        cross=elements['crosshair']['geometry']
        if state not in ('reload','sprint'):
            if state=='hip':
                radius=max(cross['minimum_gap_px'],math.tan(math.radians(sample['hip_spread_deg']))/math.tan(sample['fov_radians']/2)*540)
                for angle in cross['tick_angles_degrees']:
                    # the pack's angles have y up (90 is the top tick); the image's y is down
                    angle=math.radians(angle)
                    a=[cx+math.cos(angle)*radius,cy-math.sin(angle)*radius]
                    b=[cx+math.cos(angle)*(radius+cross['tick_length_px']),cy-math.sin(angle)*(radius+cross['tick_length_px'])]
                    self.line(a,b,self.white,cross['thickness_px'])
            self.draw.ellipse([cx-1.5,cy-1.5,cx+1.5,cy+1.5],fill=self.white)
        # Show impact styles off centre to leave the aiming state readable.
        for px,key in [(760,'DEFAULT'),(960,'HUD_DAMAGE_HEADSHOT'),(1160,'HUD_LOOT_TIER3')]:
            for dx,dy in [(1,1),(-1,1),(1,-1),(-1,-1)]:
                self.line([px+dx*7,650+dy*7],[px+dx*15,650+dy*15],self.color(key),2)
        self.text(760,683,'BODY',16,align='center')
        self.text(960,683,'HEAD',16,self.color('HUD_DAMAGE_HEADSHOT'),align='center')
        self.text(1160,683,'SHIELD',16,self.color('HUD_LOOT_TIER3'),align='center')
        self.text(1000,458,str(sample['damage']),33,self.color('HUD_DAMAGE_TEXT_BLEED'),profile_index=22)
        self.text(1110,428,str(sample['damage']),33,self.color('HUD_DAMAGE_HEADSHOT'),profile_index=22)
        self.text(1210,478,str(sample['damage']),33,self.color('HUD_LOOT_TIER3'),profile_index=22)
        for ability in self.pack['optional_elements']:
            if ability['image']:
                x,y,w,h=ability['layout']['bounds_px']
                self.panel([x,y,w,h],self.color('FRAME_LOOT_TIER1'))
                self.image(ability['image']['payload_image'],[x+8,y+6,w-16,h-12])
        self.text(60,48,'ER-APEX / T017' if self.pack['task'] == 'T017' else 'ER-FUSE / T009',29)
        self.text(60,92,'LOCAL APEX ASSETS / RECOMMENDED LAYOUT',18,self.color('HUD_LOOT_TIER1'))
        self.text(1860,52,state.upper(),24,align='right')
        self.text(1860,91,'SCHEMATIC',18,self.color('HUD_LOOT_TIER1'),align='right')
        return self.canvas


def render_previews(root, pack):
    folder=root/'preview'
    folder.mkdir(parents=True,exist_ok=True)
    states=[]
    for state in ['hip','ads','reload','sprint']:
        im=Renderer(root,pack).full_hud(state)
        im.save(folder/f'hud_{state}.png')
        states.append(im)
    Renderer(root,pack,background=False).full_hud('hip').save(folder/'hud_transparent.png')
    contact=Image.new('RGBA',(1920,1080),(38,43,49,255))
    for i,im in enumerate(states):
        contact.alpha_composite(im.resize((960,540),Image.Resampling.LANCZOS),((i%2)*960,(i//2)*540))
    contact.save(folder/'states.png')
    fonts=json.loads((root/pack['font_catalog']).read_text(encoding='utf8'))['fonts']
    profiles=[p for f in fonts for p in f['profiles']]
    renderer=Renderer(root,pack,size=(1600,120+80*len(profiles)))
    renderer.text(35,28,'LOCAL FONT ATLAS SAMPLES / MASK THRESHOLD INFERRED',24)
    for i,p in enumerate(profiles):
        renderer.text(35,105+i*80,f"{p['font_index']:02d}",22)
        if p['font_index']==10:
            renderer.text(110,105+i*80,'ICON CHARSET / 19 CODEPOINTS',22)
        else:
            renderer.text(110,105+i*80,'R-301 0123456789 OCTANE' if pack['task'] == 'T017' else 'R-301 0123456789 FUSE',26,profile_index=p['font_index'])
    renderer.canvas.save(folder/'fonts.png')
    # Small contact sheet with the exact source icons and independently labelled paths.
    assets=json.loads((root/'assets.json').read_text(encoding='utf8'))['assets']
    items=[a for a in assets if a.get('image')]
    icons=Image.new('RGBA',(1200,140*math.ceil(len(items)/5)),(38,43,49,255))
    draw=ImageDraw.Draw(icons)
    label_font=ImageFont.load_default(size=12)  # Diagnostic path labels only.
    for i,a in enumerate(items):
        x=(i%5)*240; y=(i//5)*140
        im=Image.open(root/a['image']).convert('RGBA')
        im.thumbnail((210,94),Image.Resampling.LANCZOS)
        icons.alpha_composite(im,(x+int((240-im.width)/2),y+int((100-im.height)/2)))
        name=a['name'].rsplit('/',1)[-1]
        draw.text((x+8,y+107),name[:30],font=label_font,fill=(255,255,255,255))
        draw.text((x+8,y+124),a['guid'],font=label_font,fill=(183,183,183,255))
    icons.save(folder/'assets.png')
    (folder/'README.txt').write_text('示意图使用本机图片和字体；位置、轮廓、字距、mask阈值及动态规则为推荐推断。\n'
        '护盾/Boss/血量状态为示意，备弹显示 --。BODY/HEAD/SHIELD 是颜色示例，不是三个同时发生的命中。\n'
        'hud_hip.png / hud_ads.png / hud_reload.png / hud_sprint.png 均为 1920×1080。\n'
        'fonts.png 的缺字为空白，不使用系统字体补画 HUD；assets.png 仅路径标签使用 Pillow 默认字体。\n',encoding='utf8')
