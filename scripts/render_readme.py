"""Generate the README's original looping GIF illustrations (requires Pillow)."""
from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/media'
OUT.mkdir(parents=True,exist_ok=True)
BG='#080e20'; CARD='#111c35'; LINE='#273756'; WHITE='#edf3ff'; MUTED='#91a4c4'; TEAL='#4ee0c1'; VIOLET='#ad91ff'; GOLD='#ffcc80'
def font(size,bold=False,mono=False):
    names=(["/System/Library/Fonts/Supplemental/Courier New.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"] if mono else (["/System/Library/Fonts/Supplemental/Arial Bold.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else ["/System/Library/Fonts/Supplemental/Arial.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]))
    return ImageFont.truetype(next(p for p in names if Path(p).exists()),size)
def canvas(h):
    im=Image.new('RGB',(1100,h),BG); d=ImageDraw.Draw(im)
    for y in range(h):
        t=y/h; d.line((0,y,1100,y),fill=(8+int(5*t),14+int(8*t),32+int(12*t)))
    return im,d
def text(d,xy,value,size=20,color=WHITE,bold=False,mono=False):
    d.text(xy,value,font=font(size,bold,mono),fill=color)
def box(d,rect,fill=CARD,outline=LINE,radius=18): d.rounded_rectangle(rect,radius,fill=fill,outline=outline,width=1)
def dots(d,x,y):
    for i,c in enumerate(('#ff7890','#ffcc80',TEAL)): d.ellipse((x+i*18,y,x+i*18+8,y+8),fill=c)
def save(name,frames,duration=90):
    frames[0].save(OUT/name,save_all=True,append_images=frames[1:],duration=duration,loop=0,optimize=True,disposal=2)

def hero():
    frames=[]
    phrase="Great things start with a paste."
    for n in range(52):
        im,d=canvas(420)
        for i in range(30):
            x=(i*83+n*2)%1100; y=28+(i*47)%360
            d.ellipse((x,y,x+2,y+2),fill='#233c56')
        box(d,(36,29,252,62),fill='#163733',outline='#285a4d',radius=16)
        text(d,(51,36),'LIVEPASTE  /  V4.0.0',14,TEAL,True)
        text(d,(38,95),'Your ideas.',65,WHITE,True)
        text(d,(38,169),'In sync.',65,TEAL,True)
        text(d,(42,261),'One link. Every device. Everyone together.',20,MUTED)
        for x,w,label in [(42,126,'WINDOWS'),(180,108,'macOS'),(300,102,'LINUX')]:
            box(d,(x,321,x+w,354),fill='#15203a',radius=16)
            text(d,(x+15,330),label,13,WHITE,True)
        text(d,(42,382),'NO ACCOUNTS     /     SELF-HOSTED     /     OPEN SOURCE',12,MUTED)
        box(d,(573,73,1060,348),fill='#111a30',outline='#3c4d6d',radius=20)
        dots(d,595,94); text(d,(669,89),'team-notes / Page 1',14,MUTED)
        d.line((574,123,1059,123),fill=LINE)
        text(d,(596,145),'# Something worth sharing',22,WHITE,True)
        visible=phrase[:min(len(phrase),max(0,n-3))]
        text(d,(596,194),visible,18,TEAL,mono=True)
        cursor=596+int(d.textlength(visible,font=font(18,mono=True)))
        if n%10<6: d.line((cursor+2,193,cursor+2,216),fill=TEAL,width=2)
        text(d,(596,247),'[ image.png ]   [ notes.pdf ]',17,MUTED,mono=True)
        x=810+int(36*math.sin(n/7)); y=267+int(8*math.cos(n/7))
        d.polygon([(x,y),(x+4,y+17),(x+10,y+12),(x+17,y+12)],fill=VIOLET)
        box(d,(x+17,y+16,x+94,y+38),fill='#59427e',outline='#59427e',radius=5)
        text(d,(x+24,y+20),'Your team',11,WHITE)
        d.ellipse((598,313,605,320),fill=TEAL if n%14<10 else '#2b695e')
        text(d,(615,309),'LIVE  /  CHANGES SAVED',12,TEAL,True)
        frames.append(im)
    save('hero.gif',frames)

def terminal():
    lines=[('$ LivePaste Setup.exe',WHITE),('  Installing your personal workspace...',MUTED),('  Ready on http://localhost:8090',TEAL),('  Sign-in startup enabled',TEAL),('  Background monitor: running',VIOLET)]
    frames=[]
    for n in range(58):
        im,d=canvas(274); box(d,(22,15,1078,258)); dots(d,43,34)
        text(d,(407,29),'ONE CLICK. THEN CREATE.',14,MUTED,True)
        for i,(line,color) in enumerate(lines):
            length=max(0,min(len(line),(n-i*8)*3))
            if length: text(d,(48,70+i*33),line[:length],19,color,mono=True)
        if n%10<6: text(d,(1022,215),'_',20,TEAL,mono=True)
        frames.append(im)
    save('setup.gif',frames,85)

def sync():
    frames=[]
    for n in range(66):
        im,d=canvas(324)
        for x,label,color,offset in [(24,'YOUR LAPTOP',TEAL,0),(624,'YOUR TEAM',VIOLET,2)]:
            box(d,(x,18,x+452,298)); text(d,(x+22,39),label,13,color,True)
            d.line((x+1,76,x+451,76),fill=LINE)
            line="const ideas = 'better together';"
            count=min(len(line),max(0,n-offset))
            text(d,(x+22,112),line[:count],18,WHITE,mono=True)
            text(d,(x+22,163),'Share a file. Keep the context.',17,MUTED)
            if n>24:
                box(d,(x+22,208,x+426,253),fill='#17283d',radius=9)
                text(d,(x+37,221),'[image] design-notes.png',15,color,mono=True)
        # Amber interruption becomes a reconnect, then an acknowledged state.
        disconnected=38<=n<46
        label='RECONNECT' if disconnected else ('SYNCED' if n>46 else 'LIVE SYNC')
        color=GOLD if disconnected else TEAL
        text(d,(497,112),label,12,color,True)
        d.line((492,170,605,170),fill=LINE,width=2)
        if not disconnected:
            x=493+(n*7)%110; d.ellipse((x,166,x+8,174),fill=TEAL)
        text(d,(497,206),'Yjs CRDT',12,MUTED)
        frames.append(im)
    save('sync.gif',frames)

def flow():
    frames=[]
    for n in range(44):
        im,d=canvas(158)
        labels=['01  DOWNLOAD','02  INSTALL','03  OPEN','04  KEEP CREATING']
        for i,label in enumerate(labels):
            x=24+i*270; active=(n//9)%4==i
            box(d,(x,23,x+242,92),fill='#193b3b' if active else CARD,outline=TEAL if active else LINE,radius=14)
            text(d,(x+20,48),label,16,TEAL if active else WHITE,True)
            if i<3: text(d,(x+248,45),'>',22,MUTED)
        text(d,(221,120),'STARTS AT SIGN-IN  /  RECOVERS FROM CRASHES  /  KEEPS YOUR DATA',13,MUTED)
        frames.append(im)
    save('windows.gif',frames,100)

if __name__=='__main__':
    hero(); terminal(); sync(); flow()
    for path in OUT.glob('*.gif'):
        with Image.open(path) as image:
            print(f'{path.relative_to(ROOT)}: {image.n_frames} frames, {path.stat().st_size:,} bytes')
