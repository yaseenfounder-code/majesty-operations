from decimal import Decimal
import math, re
from sqlalchemy import select, func
from .models import *
D=lambda n: Decimal(str(n))
class RuleError(ValueError): pass
def require(condition,message):
    if not condition: raise RuleError(message)
def rows(s, cls, **kw): return list(s.scalars(select(cls).filter_by(**kw)))
def audit(s,actor,action,ref='',notes=''): s.add(Audit(actor=actor,action=action,reference=str(ref),notes=notes))
def balance(s,item,loc):
    b=s.scalar(select(Balance).filter_by(item_id=item,location_id=loc))
    if not b: b=Balance(item_id=item,location_id=loc,qty=0); s.add(b); s.flush()
    return b

def reserved(s,item,loc): return sum((D(r.qty) for r in rows(s,Reservation,item_id=item,location_id=loc,active=True)),D(0))
def available(s,item,loc): return D(balance(s,item,loc).qty)-reserved(s,item,loc)
def move(s,item,qty,source,dest,kind,ref='',actor='admin'):
    qty=D(qty); require(qty.is_finite() and qty>0,'Quantity must be positive and finite'); require(source!=dest,'Choose different locations')
    require(s.get(Item,item) is not None,'Unknown item')
    for loc in (source,dest):
        if loc: require(s.get(Location,loc) is not None,'Unknown location')
    if source:
        b=balance(s,item,source); require(available(s,item,source)>=qty,'Insufficient unreserved inventory'); b.qty=D(b.qty)-qty
    if dest:
        b=balance(s,item,dest); b.qty=D(b.qty)+qty
    s.add(Ledger(item_id=item,qty=qty,source=source,destination=dest,kind=kind,reference=str(ref),actor=actor))
    audit(s,actor,kind,ref)
def bom_lines(s,product):
    b=s.scalar(select(Bom).filter_by(product_id=product)); require(b is not None,'BOM missing')
    lines=rows(s,BomLine,bom_id=b.id); require(bool(lines),'BOM missing'); return lines

def capacity(s,product,target=1):
    result=[]
    for l in bom_lines(s,product):
        c=s.get(Item,l.component_id)
        stock=sum((D(b.qty) for b in rows(s,Balance,item_id=c.id) if s.get(Location,b.location_id).kind=='RAW MATERIAL'),D(0))
        allocated=sum((D(x.qty)-D(x.consumed) for x in rows(s,Consumption,component_id=c.id) if s.get(Production,x.production_id).status in ('MATERIALS_ALLOCATED','IN_PROGRESS')),D(0))
        free=stock-allocated
        result.append(dict(id=c.id,name=c.name,sku=c.sku,unit=c.unit,available=free,per=D(l.qty),capacity=math.floor(free/D(l.qty)),need=D(l.qty)*target,short=max(D(0),D(l.qty)*target-free)))
    return dict(maximum=min(x['capacity'] for x in result),components=result,limiting=min(result,key=lambda x:x['capacity'])['name'])
def create_production(s,product,qty,actor='admin'):
    require(qty>0,'Quantity must be positive'); item=s.get(Item,product); require(item is not None and item.kind=='FINISHED','Select finished product')
    c=capacity(s,product,qty); p=Production(product_id=product,qty=qty,status='READY' if c['maximum']>=qty else 'DRAFT'); s.add(p); s.flush()
    for x in c['components']: s.add(Consumption(production_id=p.id,component_id=x['id'],qty=x['need'],consumed=0,pulled=False))
    audit(s,actor,'CREATE_PRODUCTION',p.id); return p

def production_action(s,id,action,qty=0,component=0,actor='admin'):
    p=s.get(Production,id); require(p is not None,'Unknown production order')
    require(p.status not in ('COMPLETED','CANCELLED'),'Production already closed')
    materials=rows(s,Consumption,production_id=id)
    if action=='allocate':
        require(p.status in ('DRAFT','READY'),'Already allocated')
        require(capacity(s,p.product_id)['maximum']>=p.qty,'Material shortage')
        p.status='MATERIALS_ALLOCATED'
    elif action=='pull':
        require(p.status=='MATERIALS_ALLOCATED','Allocate materials first')
        c=next((x for x in materials if x.component_id==component),None); require(c is not None,'Unknown material'); c.pulled=True
    elif action=='start':
        require(p.status=='MATERIALS_ALLOCATED' and all(x.pulled for x in materials),'Confirm all materials pulled first'); p.status='IN_PROGRESS'
    elif action=='complete':
        require(p.status=='IN_PROGRESS','Start production first'); require(0<qty<=p.qty-p.completed,'Invalid completion quantity')
        for x in materials:
            need=D(x.qty)/p.qty*qty
            for b in rows(s,Balance,item_id=x.component_id):
                if s.get(Location,b.location_id).kind!='RAW MATERIAL': continue
                take=min(need,available(s,x.component_id,b.location_id))
                if take>0: move(s,x.component_id,take,b.location_id,None,'PRODUCTION_CONSUMPTION',f'MO{id}',actor); need-=take
                if not need: break
            require(need==0,'Material shortage'); x.consumed=D(x.consumed)+D(x.qty)/p.qty*qty
        item=s.get(Item,p.product_id); move(s,item.id,qty,None,item.reserve_location,'PRODUCTION_OUTPUT',f'MO{id}',actor)
        p.completed+=qty
        if p.completed==p.qty: p.status='COMPLETED'
    elif action=='cancel': p.status='CANCELLED'
    else: raise RuleError('Unknown production action')
    audit(s,actor,'PRODUCTION_'+action.upper(),id)

def normalize(name): return re.sub(r'[^a-z0-9]','',name.lower())
def ingest(s,source,external,lines):
    require(source in ('TIKTOK','SHOPIFY'),'Demo sources only')
    require(not s.scalar(select(Order).filter_by(external_id=external)),'Duplicate order')
    o=Order(source=source,external_id=external); s.add(o); s.flush()
    for data in lines:
        require(int(data['qty'])>0,'Quantity must be positive')
        m=s.scalar(select(Mapping).filter_by(source=source,external_key=data['key']))
        exact=s.scalar(select(Item).filter_by(sku=data['key'],kind='FINISHED',active=True))
        product=m.product_id if m else exact.id if exact else None
        l=OrderLine(order_id=o.id,external_key=data['key'],title=data['title'],qty=int(data['qty']),product_id=product); s.add(l); s.flush()
        if not product:
            suggestion=next((i for i in rows(s,Item,kind='FINISHED',active=True) if normalize(i.name)==normalize(data['title'])),None)
            s.add(Review(line_id=l.id,suggested_id=suggestion.id if suggestion else None,confidence=98 if suggestion else 0))
    s.flush(); refresh_order(s,o); return o

def refresh_order(s,o):
    s.flush(); o.status='NEEDS_MAPPING' if any(l.product_id is None for l in rows(s,OrderLine,order_id=o.id)) else 'READY_TO_RESERVE'
def approve_mapping(s,review,product,actor='admin'):
    r=s.get(Review,review); require(r is not None and r.status=='PENDING','Review is closed')
    p=s.get(Item,product); require(p is not None and p.kind=='FINISHED' and p.active,'Choose active finished product')
    l=s.get(OrderLine,r.line_id); o=s.get(Order,l.order_id)
    m=s.scalar(select(Mapping).filter_by(source=o.source,external_key=l.external_key))
    if m: require(m.product_id==product,'Conflicting saved mapping')
    else: s.add(Mapping(source=o.source,external_key=l.external_key,product_id=product))
    for other in rows(s,OrderLine,external_key=l.external_key):
        parent=s.get(Order,other.order_id)
        if parent.source==o.source and parent.status in ('NEW','NEEDS_MAPPING','READY_TO_RESERVE'):
            other.product_id=product
            for rev in rows(s,Review,line_id=other.id): rev.status='APPROVED'
            refresh_order(s,parent)
    audit(s,actor,'MAPPING_APPROVED',r.id)
def reserve_order(s,id,actor='admin'):
    o=s.get(Order,id); require(o is not None and o.status in ('READY_TO_RESERVE','WAITING_FOR_INVENTORY'),'Order not ready for reservation')
    for l in rows(s,OrderLine,order_id=id):
        require(l.product_id is not None,'Mapping required'); item=s.get(Item,l.product_id); need=l.qty
        loc=item.pick_location
        require(available(s,item.id,loc)>=need,'Insufficient forward pick inventory; replenish first')
        s.add(Reservation(order_id=id,line_id=l.id,item_id=item.id,location_id=loc,qty=need,active=True)); s.flush()
        s.add(Ledger(item_id=item.id,qty=need,source=loc,kind='RESERVATION',reference=o.external_id,actor=actor))
    o.status='RESERVED'; audit(s,actor,'RESERVE',id)
def release_order(s,id,actor='admin'):
    o=s.get(Order,id); require(o is not None and o.status=='RESERVED','Only unpicked reservations can be released')
    for r in rows(s,Reservation,order_id=id,active=True):
        r.active=False; s.add(Ledger(item_id=r.item_id,qty=r.qty,source=r.location_id,kind='UNRESERVATION',reference=o.external_id,actor=actor))
    o.status='READY_TO_RESERVE'; audit(s,actor,'UNRESERVE',id)
def assign(s,tote,order=None,actor='feeder'):
    t=s.get(Tote,tote); require(t is not None and t.status=='AVAILABLE','Tote already assigned or unavailable')
    o=s.get(Order,order) if order else s.scalar(select(Order).filter_by(status='RESERVED').order_by(Order.id))
    require(o is not None and o.status=='RESERVED','No eligible reserved order')
    require(not s.scalar(select(Tote).filter_by(order_id=o.id)),'Order already assigned')
    t.order_id=o.id; t.status='PICKING'; o.status='PICKING'; s.add(Assignment(tote_id=t.id,order_id=o.id)); audit(s,actor,'TOTE_ASSIGNED',o.id); return o

def pick(s,tote,barcode,qty=1,actor='feeder'):
    t=s.get(Tote,tote); require(t is not None and t.status=='PICKING','Tote not picking'); require(qty>0,'Invalid quantity')
    item=s.scalar(select(Item).where((Item.barcode==barcode)|(Item.sku==barcode)))
    l=next((l for l in rows(s,OrderLine,order_id=t.order_id) if item and l.product_id==item.id and l.picked<l.qty),None)
    require(l is not None,'WRONG PRODUCT — scan an expected SKU'); require(l.picked+qty<=l.qty,'Too many units')
    r=s.scalar(select(Reservation).filter_by(line_id=l.id,active=True)); require(r is not None and r.qty>=qty,'Reservation missing')
    r.qty-=qty
    if not r.qty: r.active=False
    s.flush(); move(s,item.id,qty,r.location_id,'TOTE:'+t.id,'PICK',f'ORDER{t.order_id}',actor)
    l.picked+=qty; s.add(PickEvent(order_id=t.order_id,line_id=l.id,barcode=barcode,qty=qty,actor=actor))
def finish_pick(s,tote,actor='feeder'):
    t=s.get(Tote,tote); require(t is not None and t.status=='PICKING','Tote not picking')
    require(all(l.picked==l.qty for l in rows(s,OrderLine,order_id=t.order_id)),'Pick all products first')
    t.status='READY_TO_PACK'; s.get(Order,t.order_id).status='READY_TO_PACK'; audit(s,actor,'PICK_COMPLETE',t.order_id)
def start_pack(s,tote,actor='packer'):
    t=s.get(Tote,tote); require(t is not None and t.status=='READY_TO_PACK','Complete picking before packing')
    t.status='PACKING'; s.get(Order,t.order_id).status='PACKING'
    ps=PackingSession(order_id=t.order_id,tote_id=t.id,packer=actor,camera_reference=f'demo://camera/{t.order_id}'); s.add(ps); audit(s,actor,'CAMERA_START',t.order_id)
def verify_pack(s,tote,barcode,qty=1,actor='packer'):
    t=s.get(Tote,tote); require(t is not None and t.status=='PACKING','Start packing first'); require(qty>0,'Invalid quantity')
    item=s.scalar(select(Item).where((Item.sku==barcode)|(Item.barcode==barcode)))
    l=next((l for l in rows(s,OrderLine,order_id=t.order_id) if item and l.product_id==item.id and l.packed<l.qty),None)
    require(l is not None,'PACKING MISMATCH — wrong product'); require(l.packed+qty<=l.qty,'Too many units')
    move(s,item.id,qty,'TOTE:'+t.id,'PACK-STATION-01','PACK',f'ORDER{t.order_id}',actor); l.packed+=qty; s.add(PackEvent(order_id=t.order_id,line_id=l.id,qty=qty,actor=actor))
def label(s,tote,actor='packer'):
    t=s.get(Tote,tote); require(t is not None and t.status=='PACKING','Start packing first')
    require(all(l.packed==l.qty for l in rows(s,OrderLine,order_id=t.order_id)),'Verify all products first')
    sh=s.scalar(select(Shipment).filter_by(order_id=t.order_id))
    if not sh:
        from .adapters import DemoShipping
        sh=Shipment(order_id=t.order_id,tracking=DemoShipping().tracking(t.order_id)); s.add(sh); s.flush(); audit(s,actor,'DEMO_LABEL',t.order_id)
    return sh

def finish_pack(s,tote,actor='packer'):
    t=s.get(Tote,tote); require(t is not None and t.status=='PACKING','Complete picking and start packing first')
    require(all(l.packed==l.qty for l in rows(s,OrderLine,order_id=t.order_id)),'Verify all contents before completion')
    sh=s.scalar(select(Shipment).filter_by(order_id=t.order_id)); require(sh is not None,'Generate demo label first')
    for l in rows(s,OrderLine,order_id=t.order_id): move(s,l.product_id,l.qty,'PACK-STATION-01',None,'SHIP',f'ORDER{t.order_id}',actor)
    ps=s.scalar(select(PackingSession).filter_by(order_id=t.order_id)); ps.completed=now()
    s.get(Order,t.order_id).status='SHIPPED'
    for a in rows(s,Assignment,tote_id=t.id,order_id=t.order_id): a.completed=now()
    audit(s,actor,'ORDER_COMPLETE',t.order_id); t.status='AVAILABLE'; t.order_id=None
