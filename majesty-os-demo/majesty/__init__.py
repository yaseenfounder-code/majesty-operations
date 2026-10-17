import os, secrets
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, request, session, redirect, url_for, render_template, flash, g, abort, Response
from sqlalchemy import select, func
from .db import database
from .models import *
from . import services as svc
from .seed import seed
from .adapters import DemoShipping

def create_app(database_url=None,testing=False):
    app=Flask(__name__); app.config.update(SECRET_KEY=secrets.token_hex(32),TESTING=testing,MAX_CONTENT_LENGTH=1024*1024,SESSION_COOKIE_SAMESITE='Strict',SESSION_COOKIE_HTTPONLY=True)
    folder=Path(__file__).resolve().parent.parent/'instance'; folder.mkdir(exist_ok=True)
    app.session_factory=database(database_url or os.environ.get('DATABASE_URL',f'sqlite:///{folder}/majesty.db'))
    @app.cli.command('seed')
    def seed_command():
        with app.session_factory.begin() as s: print('Demo data seeded.' if seed(s) else 'Database already seeded; unchanged.')
    @app.before_request
    def before():
        g.db=app.session_factory(); g.actor=session.get('user','admin'); g.user=g.db.get(User,g.actor)
        if 'csrf' not in session: session['csrf']=secrets.token_hex(24)
        if request.method=='POST' and request.form.get('csrf')!=session['csrf']: abort(400,'Invalid form token')
    @app.teardown_request
    def teardown(error):
        if hasattr(g,'db'): g.db.close()
    @app.context_processor
    def context():
        return dict(csrf=session.get('csrf'),actor=g.actor,role=g.user.role if g.user else 'ADMIN',nav=NAV,item=lambda id:g.db.get(Item,id),order=lambda id:g.db.get(Order,id),lines=lambda id:svc.rows(g.db,OrderLine,order_id=id),fmt=lambda n:f'{float(n or 0):,.3f}'.rstrip('0').rstrip('.'),available=lambda i,l:svc.available(g.db,i,l),reserved=lambda i,l:svc.reserved(g.db,i,l))
    def authorize(page):
        role=g.user.role if g.user else 'ADMIN'
        allowed={'MANUFACTURER':['manufacturing','boms','raw-materials'],'FEEDER':['feeder','totes'],'PACKER':['packing','totes']}
        if role!='ADMIN' and page not in allowed.get(role,[]): abort(403)
    @app.get('/')
    def root():
        role=g.user.role if g.user else 'ADMIN'; return redirect(url_for('page',name={'MANUFACTURER':'manufacturing','FEEDER':'feeder','PACKER':'packing'}.get(role,'dashboard')))
    @app.get('/health')
    def health():
        g.db.execute(select(func.count(Item.id))); return {'status':'ok','mode':'demo'}
    @app.get('/<name>')
    def page(name):
        if name not in dict(NAV): abort(404)
        authorize(name); s=g.db
        data={cls.__name__:svc.rows(s,cls) for cls in [Item,Location,Balance,Bom,BomLine,Production,Consumption,Order,OrderLine,Review,Mapping,Reservation,Tote,Ledger,Audit,ExceptionEvent,PackingSession,Shipment,User]}
        data['products']=[i for i in data['Item'] if i.kind=='FINISHED']; data['materials']=[i for i in data['Item'] if i.kind=='RAW']
        data['capacity']=None
        if name=='boms' and request.args.get('product'):
            try: data['capacity']=svc.capacity(s,int(request.args['product']),max(1,int(request.args.get('target',1))))
            except (ValueError,svc.RuleError): flash('Choose a valid product and target','error')
        today=datetime.now(timezone.utc).date()
        data['today_received']=sum(1 for o in data['Order'] if o.created.date()==today)
        data['today_picked']=sum(1 for a in data['Audit'] if a.action=='PICK_COMPLETE' and a.created.date()==today)
        data['today_packed']=sum(1 for p in data['PackingSession'] if p.completed and p.completed.date()==today)
        data['today_manufactured']=sum(e.qty for e in data['Ledger'] if e.kind=='PRODUCTION_OUTPUT' and e.created.date()==today)
        data['selected_product']=request.args.get('product',type=int)
        return render_template('app.html',page=name,**data)
    @app.post('/action/<action>')
    def action(action):
        s=g.db; f=request.form; actor=g.actor
        page_for={'production':'manufacturing','create-production':'manufacturing','approve':'mapping-review','reject':'mapping-review','reserve':'orders','release':'orders','ingest':'orders','assign':'feeder','pick':'feeder','finish-pick':'feeder','start-pack':'packing','verify':'packing','label':'packing','finish-pack':'packing','transfer':'replenishment','receive':'inventory','save-bom':'boms','template':'boms','resolve':'exceptions'}
        def num(k): return int(f[k])
        if action=='login':
            require_user=s.get(User,f.get('user')); 
            if not require_user: abort(400)
            session['user']=require_user.id; return redirect('/')
        if action not in page_for: abort(404)
        authorize(page_for[action])
        try:
            if action=='create-production': svc.create_production(s,num('product'),num('qty'),actor)
            elif action=='production': svc.production_action(s,num('id'),f['operation'],int(f.get('qty') or 0),int(f.get('component') or 0),actor)
            elif action=='approve': svc.approve_mapping(s,num('id'),num('product'),actor)
            elif action=='reject':
                r=s.get(Review,num('id')); svc.require(r is not None and r.status=='PENDING','Review closed'); r.status='REJECTED'; s.get(Order,s.get(OrderLine,r.line_id).order_id).status='EXCEPTION'; svc.audit(s,actor,'MAPPING_REJECTED',r.id)
            elif action=='reserve': svc.reserve_order(s,num('id'),actor)
            elif action=='release': svc.release_order(s,num('id'),actor)
            elif action=='ingest': svc.ingest(s,f['source'],f['external'],[dict(key=f['key'],title=f['title'],qty=num('qty'))])
            elif action=='assign': svc.assign(s,f['tote'],actor=actor)
            elif action=='pick': svc.pick(s,f['tote'],f['barcode'],num('qty'),actor)
            elif action=='finish-pick': svc.finish_pick(s,f['tote'],actor)
            elif action=='start-pack': svc.start_pack(s,f['tote'],actor)
            elif action=='verify': svc.verify_pack(s,f['tote'],f['barcode'],num('qty'),actor)
            elif action=='label':
                sh=svc.label(s,f['tote'],actor); s.commit(); return Response(DemoShipping().label_pdf(sh.tracking),mimetype='application/pdf',headers={'Content-Disposition':f'attachment; filename="demo-label-{sh.id}.pdf"'})
            elif action=='finish-pack': svc.finish_pack(s,f['tote'],actor)
            elif action=='transfer':
                i=s.get(Item,num('item')); svc.require(i is not None and i.kind=='FINISHED','Transfer finished goods only')
                src=s.get(Location,f['source']); dest=s.get(Location,f['destination']); svc.require(src is not None and dest is not None and src.kind in ('RESERVE FINISHED GOODS','FORWARD PICK','RETURNS') and dest.kind in ('RESERVE FINISHED GOODS','FORWARD PICK','DAMAGED'),'Invalid transfer locations')
                svc.move(s,i.id,f['qty'],src.id,dest.id,'TRANSFER','MANUAL',actor)
            elif action=='receive':
                loc=s.get(Location,f['destination']); i=s.get(Item,num('item'))
                svc.require(i is not None and loc is not None and ((i.kind=='RAW' and loc.kind=='RAW MATERIAL') or (i.kind=='FINISHED' and loc.kind in ('FORWARD PICK','RESERVE FINISHED GOODS','RETURNS'))),'Choose a compatible inventory location')
                svc.move(s,i.id,f['qty'],None,loc.id,'RECEIPT','DEMO-RECEIPT',actor)
            elif action in ('save-bom','template'):
                product=num('product'); b=s.scalar(select(Bom).filter_by(product_id=product)); svc.require(b is not None,'Unknown BOM')
                svc.require(not any(p.product_id==product and p.status not in ('COMPLETED','CANCELLED') for p in svc.rows(s,Production)),'Close open production orders before editing BOM')
                if action=='template':
                    template=s.get(Bom,num('template')); svc.require(template is not None and template.template,'Choose BOM template')
                    for l in svc.rows(s,BomLine,bom_id=template.id):
                        current=s.scalar(select(BomLine).filter_by(bom_id=b.id,component_id=l.component_id))
                        if current: current.qty=l.qty
                        else: s.add(BomLine(bom_id=b.id,component_id=l.component_id,qty=l.qty))
                else:
                    component=num('component'); material=s.get(Item,component); svc.require(material is not None and material.kind=='RAW','Select raw material'); qty=svc.D(f['qty']); svc.require(qty.is_finite() and qty>=0,'Quantity must be finite and nonnegative')
                    line=s.scalar(select(BomLine).filter_by(bom_id=b.id,component_id=component))
                    if qty==0:
                        if line: s.delete(line)
                    elif line: line.qty=qty
                    else: s.add(BomLine(bom_id=b.id,component_id=component,qty=qty))
                svc.audit(s,actor,'BOM_UPDATED',product)
            elif action=='resolve':
                e=s.get(ExceptionEvent,num('id')); svc.require(e is not None,'Unknown exception'); e.resolved=True; svc.audit(s,actor,'EXCEPTION_RESOLVED',e.id)
            s.commit(); flash('Saved successfully','success')
        except (svc.RuleError, ValueError, KeyError, ArithmeticError) as e:
            s.rollback(); message=str(e)
            if action=='reserve':
                failed=s.get(Order,int(f['id'])) if f.get('id','').isdigit() else None
                if failed and failed.status in ('READY_TO_RESERVE','WAITING_FOR_INVENTORY'): failed.status='WAITING_FOR_INVENTORY'
            s.add(ExceptionEvent(kind={'pick':'WRONG_BARCODE_SCANNED','verify':'PACKING_MISMATCH','reserve':'INSUFFICIENT_INVENTORY','production':'PRODUCTION_EXCEPTION'}.get(action,'WORKFLOW_EXCEPTION'),reference=f.get('id',f.get('tote','')),message=message))
            svc.audit(s,actor,'REJECTED_'+action.upper(),notes=message); s.commit(); flash(message,'error')
        return redirect(url_for('page',name=page_for[action]))
    return app
NAV=[('dashboard','Dashboard'),('orders','Orders'),('mapping-review','Mapping Review'),('inventory','Inventory'),('raw-materials','Raw Materials'),('products','Products'),('manufacturing','Manufacturing'),('boms','BOMs'),('locations','Locations'),('replenishment','Replenishment'),('feeder','Feeder'),('packing','Packing'),('totes','Totes'),('exceptions','Exceptions'),('audit-log','Audit Log'),('settings','Settings')]
