import pytest
from sqlalchemy import select, func
from majesty import create_app, NAV
from majesty.models import *
from majesty.seed import seed
from majesty import services as w

@pytest.fixture
def app(tmp_path):
    a=create_app('sqlite:///'+str(tmp_path/'test.db'),testing=True)
    with a.session_factory.begin() as s: seed(s)
    return a
@pytest.fixture
def db(app):
    with app.session_factory.begin() as s: yield s

def vanaco(s): return s.scalar(select(Item).filter_by(sku='MJS-FR-0362-VA-30'))
def new_order(s,p,qty=2,external='TEST'):
    return w.ingest(s,'SHOPIFY',external,[dict(key=p.sku,title=p.name,qty=qty)])
def prepared(s):
    p=vanaco(s); o=new_order(s,p); w.reserve_order(s,o.id); w.assign(s,'TOTE-001',o.id); return p,o

def test_capacity_and_shortages(db):
    c=w.capacity(db,vanaco(db).id,500)
    assert c['maximum']==180 and 'Back Label' in c['limiting']
    oil=next(x for x in c['components'] if x['sku']=='OIL-0362'); assert oil['short']==2700
    back=next(x for x in c['components'] if x['sku']=='LBL-0362-30-B'); assert back['short']==320

def test_production_cannot_exceed_materials(db):
    p=w.create_production(db,vanaco(db).id,181)
    with pytest.raises(w.RuleError,match='shortage'): w.production_action(db,p.id,'allocate')
    assert p.status=='DRAFT'

def test_production_consumes_outputs_partial_and_cancel(db):
    item=vanaco(db); before=w.balance(db,item.id,item.reserve_location).qty
    p=w.create_production(db,item.id,20); oil=db.scalar(select(Item).filter_by(sku='OIL-0362')); raw=w.balance(db,oil.id,'OIL-A-12').qty
    assert w.balance(db,oil.id,'OIL-A-12').qty==raw
    w.production_action(db,p.id,'allocate')
    assert w.capacity(db,item.id)['maximum']==160
    for c in w.rows(db,Consumption,production_id=p.id): w.production_action(db,p.id,'pull',component=c.component_id)
    w.production_action(db,p.id,'start'); w.production_action(db,p.id,'complete',qty=7)
    assert w.balance(db,oil.id,'OIL-A-12').qty==raw-63
    assert w.balance(db,item.id,item.reserve_location).qty==before+7
    assert p.status=='IN_PROGRESS' and p.completed==7
    w.production_action(db,p.id,'cancel'); assert p.status=='CANCELLED'
    assert w.capacity(db,item.id)['maximum']==173

def test_production_complete_only_once(db):
    p=w.create_production(db,vanaco(db).id,2); w.production_action(db,p.id,'allocate')
    with pytest.raises(w.RuleError): w.production_action(db,p.id,'start')
    for c in w.rows(db,Consumption,production_id=p.id): w.production_action(db,p.id,'pull',component=c.component_id)
    w.production_action(db,p.id,'start'); w.production_action(db,p.id,'complete',qty=2)
    assert p.status=='COMPLETED'
    with pytest.raises(w.RuleError): w.production_action(db,p.id,'complete',qty=2)
    assert len(w.rows(db,Ledger,kind='PRODUCTION_CONSUMPTION',reference=f'MO{p.id}'))==8

def test_transfer_preserves_totals(db):
    p=vanaco(db); before=sum(b.qty for b in w.rows(db,Balance,item_id=p.id))
    w.move(db,p.id,28,p.reserve_location,p.pick_location,'TRANSFER')
    assert sum(b.qty for b in w.rows(db,Balance,item_id=p.id))==before
    assert w.balance(db,p.id,p.pick_location).qty==53

def test_reservation_limit_and_physical_stock(db):
    p=vanaco(db); a=new_order(db,p,20); b=new_order(db,p,6,'TEST2'); w.reserve_order(db,a.id)
    assert w.balance(db,p.id,p.pick_location).qty==25
    assert w.available(db,p.id,p.pick_location)==5
    with pytest.raises(w.RuleError): w.reserve_order(db,b.id)
    with pytest.raises(w.RuleError): w.move(db,p.id,6,p.pick_location,p.reserve_location,'TRANSFER')
    w.release_order(db,a.id); assert w.available(db,p.id,p.pick_location)==25

def test_mapping_approval_saved_and_reused(db):
    o=db.scalar(select(Order).filter_by(external_id='TT10001')); l=w.rows(db,OrderLine,order_id=o.id)[0]; r=w.rows(db,Review,line_id=l.id)[0]
    assert r.confidence==98
    w.approve_mapping(db,r.id,vanaco(db).id)
    assert o.status=='READY_TO_RESERVE'
    future=w.ingest(db,'TIKTOK','FUTURE',[dict(key=l.external_key,title='Different title',qty=1)])
    assert future.status=='READY_TO_RESERVE' and w.rows(db,OrderLine,order_id=future.id)[0].product_id==vanaco(db).id
    weak=db.scalar(select(Review).filter_by(confidence=0)); assert weak.suggested_id is None

def test_wrong_pick_and_quantity(db):
    p,o=prepared(db)
    with pytest.raises(w.RuleError,match='WRONG PRODUCT'): w.pick(db,'TOTE-001','NOPE')
    with pytest.raises(w.RuleError): w.pick(db,'TOTE-001',p.sku,3)
    assert w.rows(db,OrderLine,order_id=o.id)[0].picked==0
    with pytest.raises(w.RuleError): w.finish_pick(db,'TOTE-001')

def test_tote_not_double_assigned(db):
    p,o=prepared(db); second=new_order(db,p,1,'SECOND'); w.reserve_order(db,second.id)
    with pytest.raises(w.RuleError): w.assign(db,'TOTE-001',second.id)
    with pytest.raises(w.RuleError): w.assign(db,'TOTE-002',o.id)

def test_cannot_pack_before_picking(db):
    p,o=prepared(db)
    with pytest.raises(w.RuleError): w.start_pack(db,'TOTE-001')
    with pytest.raises(w.RuleError): w.finish_pack(db,'TOTE-001')

def test_full_fulfillment_and_ledger(db):
    p,o=prepared(db); total=sum(b.qty for b in w.rows(db,Balance,item_id=p.id))
    w.pick(db,'TOTE-001',p.barcode,2); w.finish_pick(db,'TOTE-001'); w.start_pack(db,'TOTE-001')
    with pytest.raises(w.RuleError): w.finish_pack(db,'TOTE-001')
    with pytest.raises(w.RuleError): w.verify_pack(db,'TOTE-001','WRONG')
    w.verify_pack(db,'TOTE-001',p.sku,2)
    with pytest.raises(w.RuleError,match='label'): w.finish_pack(db,'TOTE-001')
    sh=w.label(db,'TOTE-001'); assert w.label(db,'TOTE-001').id==sh.id
    w.finish_pack(db,'TOTE-001')
    assert o.status=='SHIPPED' and db.get(Tote,'TOTE-001').status=='AVAILABLE'
    assert sum(b.qty for b in w.rows(db,Balance,item_id=p.id))==total-2
    assert w.rows(db,PackingSession,order_id=o.id)[0].completed
    kinds={e.kind for e in w.rows(db,Ledger,item_id=p.id)}
    assert {'RESERVATION','PICK','PACK','SHIP'}<=kinds
    from majesty.adapters import DemoShipping
    assert DemoShipping().label_pdf(sh.tracking).startswith(b'%PDF')

def test_all_pages_csrf_roles(app):
    c=app.test_client()
    for name,_ in NAV: assert c.get('/'+name).status_code==200
    assert c.get('/health').json=={'status':'ok','mode':'demo'}
    assert c.post('/action/reserve',data={'id':1}).status_code==400
    with c.session_transaction() as session: token=session['csrf']
    assert c.post('/action/login',data={'csrf':token,'user':'feeder'}).status_code==302
    assert c.get('/manufacturing').status_code==403
    assert c.post('/action/receive',data={'csrf':token}).status_code==403
    assert c.get('/feeder').status_code==200

def test_atomic_rollback_and_exception(app):
    with app.session_factory.begin() as s:
        p=vanaco(s); second=s.scalar(select(Item).filter_by(sku='MJS-FR-0362-VA-50'))
        o=w.ingest(s,'SHOPIFY','ATOMIC',[dict(key=p.sku,title=p.name,qty=2),dict(key=second.sku,title=second.name,qty=1000)]); id=o.id; pid=p.id
    c=app.test_client(); c.get('/')
    with c.session_transaction() as ss: token=ss['csrf']
    response=c.post('/action/reserve',data={'csrf':token,'id':id},follow_redirects=True)
    assert b'Insufficient' in response.data
    with app.session_factory.begin() as s:
        assert w.reserved(s,pid,'PICK-A-12')==0
        assert s.get(Order,id).status=='WAITING_FOR_INVENTORY'
        assert w.rows(s,ExceptionEvent,kind='INSUFFICIENT_INVENTORY')

def test_seed_repeatable(db):
    before=db.scalar(select(func.count(Item.id))); assert seed(db) is False
    assert db.scalar(select(func.count(Item.id)))==before

def test_browser_core_loop(app):
    c=app.test_client(); c.get('/manufacturing')
    with c.session_transaction() as ss: token=ss['csrf']
    def post(action,**data):
        r=c.post('/action/'+action,data={'csrf':token,**data},follow_redirects=True)
        assert r.status_code==200
        assert b'class="notice error"' not in r.data
        return r
    with app.session_factory.begin() as s:
        p=vanaco(s); pid=p.id; sku=p.sku
    post('create-production',product=pid,qty=3)
    with app.session_factory.begin() as s:
        mo=s.scalar(select(Production).order_by(Production.id.desc())); mid=mo.id
        components=[x.component_id for x in w.rows(s,Consumption,production_id=mid)]
    post('production',id=mid,operation='allocate')
    for component in components: post('production',id=mid,operation='pull',component=component)
    post('production',id=mid,operation='start'); post('production',id=mid,operation='complete',qty=3)
    post('transfer',item=pid,qty=3,source='RESERVE-R03',destination='PICK-A-12')
    post('ingest',source='TIKTOK',external='BROWSER',key='browser-vanaco',title='Vanaco 30ML',qty=3)
    with app.session_factory.begin() as s:
        o=s.scalar(select(Order).filter_by(external_id='BROWSER')); oid=o.id
        review=w.rows(s,Review,line_id=w.rows(s,OrderLine,order_id=oid)[0].id)[0].id
    post('approve',id=review,product=pid); post('reserve',id=oid)
    # Assigns the earliest reserved order (only this order is reserved in this test).
    post('assign',tote='TOTE-001'); post('pick',tote='TOTE-001',barcode=sku,qty=3)
    post('finish-pick',tote='TOTE-001'); post('start-pack',tote='TOTE-001')
    post('verify',tote='TOTE-001',barcode=sku,qty=3)
    r=post('label',tote='TOTE-001'); assert r.mimetype=='application/pdf' and r.data.startswith(b'%PDF')
    post('finish-pack',tote='TOTE-001')
    with app.session_factory.begin() as s:
        assert s.get(Order,oid).status=='SHIPPED'
        assert w.rows(s,Shipment,order_id=oid) and w.rows(s,PackingSession,order_id=oid)[0].completed
        assert s.get(Tote,'TOTE-001').order_id is None

def test_invalid_receipt_and_nonfinite_quantities(app,db):
    p=vanaco(db)
    for qty in ('NaN','Infinity','-1','0'):
        with pytest.raises(w.RuleError): w.move(db,p.id,qty,None,p.pick_location,'RECEIPT')

def test_simultaneous_reservations_cannot_oversell(app):
    from concurrent.futures import ThreadPoolExecutor
    with app.session_factory.begin() as s:
        p=vanaco(s); ids=[new_order(s,p,20,'RACE'+str(n)).id for n in range(2)]; pid=p.id
    def reserve(id):
        try:
            with app.session_factory.begin() as s: w.reserve_order(s,id)
            return True
        except w.RuleError: return False
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(reserve,ids))
    assert sorted(results)==[False,True]
    with app.session_factory.begin() as s:
        assert w.reserved(s,pid,'PICK-A-12')==20
        assert w.balance(s,pid,'PICK-A-12').qty==25
