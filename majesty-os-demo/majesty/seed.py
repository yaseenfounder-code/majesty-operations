from .services import *
from .adapters import DemoMarketplace

def seed(s):
    if s.scalar(select(Item.id).limit(1)): return False
    for id,kind in [('OIL-A-12','RAW MATERIAL'),('PKG-A-01','RAW MATERIAL'),('LABEL-A-0362','RAW MATERIAL'),('MFG-01','MANUFACTURING'),('WIP-01','WORK IN PROCESS'),('RESERVE-R03','RESERVE FINISHED GOODS'),('PICK-A-12','FORWARD PICK'),('PACK-STATION-01','PACKING'),('DAMAGED-01','DAMAGED'),('RETURNS-01','RETURNS')]: s.add(Location(id=id,kind=kind))
    for role in ('ADMIN','MANUFACTURER','FEEDER','PACKER'): s.add(User(id=role.lower(),role=role))
    for n in range(1,9):
        id=f'TOTE-{n:03d}'; s.add(Tote(id=id)); s.add(Location(id='TOTE:'+id,kind='TOTE'))
    s.flush()
    def item(sku,name,kind='RAW',unit='each',stock=1000,loc='PKG-A-01',**kw):
        i=Item(sku=sku,name=name,kind=kind,unit=unit,barcode='DEMO-'+sku,**kw); s.add(i); s.flush()
        if stock: move(s,i.id,stock,None,loc,'RECEIPT','DEMO-SEED')
        return i
    base=item('BASE','Perfume base / alcohol',unit='mL',stock=50000,loc='OIL-A-12')
    atom=item('ATOM','Standard Atomizer'); cap=item('CAP','Standard Cap')
    common={}
    for size in (30,50,100):
        bottle=item(f'BOTTLE-{size}',f'{size} mL Bottle',stock=600)
        box=item(f'BOX-{size}',f'{size} mL Box',stock=600)
        common[size]=[(base,size*.7),(bottle,1),(atom,1),(cap,1),(box,1)]
        b=Bom(name=f'Standard {size} mL template',template=True); s.add(b); s.flush()
        for c,q in common[size]: s.add(BomLine(bom_id=b.id,component_id=c.id,qty=q))
    specs=[('Vanaco','0362','VA',30),('Vanaco','0362','VA',50),('Vanaco','0362','VA',100),('Rouge Extrait','0002','RO',30),('Rouge Extrait','0002','RO',50),('Foresight','0003','FO',30),('Lafayette','0004','LF',30),('Laro','0005','LA',30),('Kavior','0006','KA',30),('Arabelle','0007','AR',30)]
    oils={}; products=[]
    for name,scent,code,size in specs:
        if scent not in oils: oils[scent]=item('OIL-'+scent,name+' Fragrance Oil',unit='mL',stock=1800,loc='OIL-A-12')
        front=item(f'LBL-{scent}-{size}-F',f'{name} {size} Front Label',stock=230,loc='LABEL-A-0362')
        back=item(f'LBL-{scent}-{size}-B',f'{name} {size} Back Label',stock=180,loc='LABEL-A-0362')
        p=item(f'MJS-FR-{scent}-{code}-{size}',f'{name} {size} mL',kind='FINISHED',stock=0,size=size,scent=scent); products.append(p)
        move(s,p.id,25,None,p.pick_location,'RECEIPT','DEMO-SEED'); move(s,p.id,188,None,p.reserve_location,'RECEIPT','DEMO-SEED')
        b=Bom(product_id=p.id,name=p.name); s.add(b); s.flush()
        for c,q in common[size]+[(oils[scent],size*.3),(front,1),(back,1)]: s.add(BomLine(bom_id=b.id,component_id=c.id,qty=q))
    s.flush()
    create_production(s,products[0].id,20); create_production(s,products[4].id,200)
    for o in DemoMarketplace().fetch_orders(): ingest(s,**o)
    ingest(s,'SHOPIFY','SH10003',[{'key':products[5].sku,'title':products[5].name,'qty':3}])
    audit(s,'admin','DEMO_SEEDED'); return True
