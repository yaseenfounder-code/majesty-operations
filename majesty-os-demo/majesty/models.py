from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Numeric, ForeignKey, UniqueConstraint, DateTime, Text, Boolean, CheckConstraint
from sqlalchemy.orm import declarative_base
Base = declarative_base()
def now(): return datetime.now(timezone.utc)
class Item(Base):
    __tablename__='products_components'
    id=Column(Integer,primary_key=True); sku=Column(String,unique=True,nullable=False); name=Column(String,nullable=False); kind=Column(String,nullable=False); barcode=Column(String,unique=True); unit=Column(String,default='each'); size=Column(Integer); scent=Column(String); active=Column(Boolean,default=True); category=Column(String,default='Fragrance'); supplier=Column(String,default='Demo supply'); lot=Column(String,default='DEMO-001'); reorder=Column(Numeric(14,3),default=10); pick_target=Column(Integer,default=40); pick_location=Column(String,default='PICK-A-12'); reserve_location=Column(String,default='RESERVE-R03')
class Location(Base):
    __tablename__='locations'
    id=Column(String,primary_key=True); kind=Column(String,nullable=False)
class Balance(Base):
    __tablename__='inventory_balances'
    id=Column(Integer,primary_key=True); item_id=Column(ForeignKey(Item.id),nullable=False); location_id=Column(ForeignKey(Location.id),nullable=False); qty=Column(Numeric(14,3),nullable=False,default=0)
    __table_args__=(UniqueConstraint('item_id','location_id'),CheckConstraint('qty >= 0'))
class Ledger(Base):
    __tablename__='inventory_transactions'
    id=Column(Integer,primary_key=True); created=Column(DateTime,default=now); item_id=Column(ForeignKey(Item.id),nullable=False); qty=Column(Numeric(14,3),nullable=False); source=Column(ForeignKey(Location.id)); destination=Column(ForeignKey(Location.id)); kind=Column(String,nullable=False); reference=Column(String); actor=Column(String,default='admin'); notes=Column(Text,default='')
class Bom(Base):
    __tablename__='boms'
    id=Column(Integer,primary_key=True); product_id=Column(ForeignKey(Item.id),unique=True); name=Column(String); template=Column(Boolean,default=False)
class BomLine(Base):
    __tablename__='bom_lines'
    id=Column(Integer,primary_key=True); bom_id=Column(ForeignKey(Bom.id),nullable=False); component_id=Column(ForeignKey(Item.id),nullable=False); qty=Column(Numeric(14,3),nullable=False)
    __table_args__=(UniqueConstraint('bom_id','component_id'),CheckConstraint('qty > 0'))
class Production(Base):
    __tablename__='production_orders'
    id=Column(Integer,primary_key=True); product_id=Column(ForeignKey(Item.id)); qty=Column(Integer,nullable=False); completed=Column(Integer,default=0); status=Column(String,default='DRAFT'); created=Column(DateTime,default=now)
class Consumption(Base):
    __tablename__='production_material_consumption'
    id=Column(Integer,primary_key=True); production_id=Column(ForeignKey(Production.id)); component_id=Column(ForeignKey(Item.id)); qty=Column(Numeric(14,3)); pulled=Column(Boolean,default=False); consumed=Column(Numeric(14,3),default=0)
class Order(Base):
    __tablename__='customer_orders'
    id=Column(Integer,primary_key=True); external_id=Column(String,unique=True); source=Column(String); status=Column(String,default='NEW'); created=Column(DateTime,default=now)
class OrderLine(Base):
    __tablename__='order_lines'
    id=Column(Integer,primary_key=True); order_id=Column(ForeignKey(Order.id)); external_key=Column(String); title=Column(String); product_id=Column(ForeignKey(Item.id)); qty=Column(Integer,nullable=False); picked=Column(Integer,default=0); packed=Column(Integer,default=0)
class Mapping(Base):
    __tablename__='marketplace_mappings'
    id=Column(Integer,primary_key=True); source=Column(String); external_key=Column(String); product_id=Column(ForeignKey(Item.id)); __table_args__=(UniqueConstraint('source','external_key'),)
class Review(Base):
    __tablename__='mapping_reviews'
    id=Column(Integer,primary_key=True); line_id=Column(ForeignKey(OrderLine.id),unique=True); suggested_id=Column(ForeignKey(Item.id)); confidence=Column(Integer,default=0); status=Column(String,default='PENDING')
class Reservation(Base):
    __tablename__='inventory_reservations'
    id=Column(Integer,primary_key=True); order_id=Column(ForeignKey(Order.id)); line_id=Column(ForeignKey(OrderLine.id)); item_id=Column(ForeignKey(Item.id)); location_id=Column(ForeignKey(Location.id)); qty=Column(Integer); active=Column(Boolean,default=True)
class Tote(Base):
    __tablename__='totes'
    id=Column(String,primary_key=True); status=Column(String,default='AVAILABLE'); order_id=Column(ForeignKey(Order.id),unique=True)
class Assignment(Base):
    __tablename__='tote_assignments'
    id=Column(Integer,primary_key=True); tote_id=Column(ForeignKey(Tote.id)); order_id=Column(ForeignKey(Order.id)); created=Column(DateTime,default=now); completed=Column(DateTime)
class PickEvent(Base):
    __tablename__='pick_events'
    id=Column(Integer,primary_key=True); order_id=Column(ForeignKey(Order.id)); line_id=Column(ForeignKey(OrderLine.id)); barcode=Column(String); qty=Column(Integer); actor=Column(String); created=Column(DateTime,default=now)
class PackEvent(Base):
    __tablename__='pack_events'
    id=Column(Integer,primary_key=True); order_id=Column(ForeignKey(Order.id)); line_id=Column(ForeignKey(OrderLine.id)); qty=Column(Integer); actor=Column(String); created=Column(DateTime,default=now)
class PackingSession(Base):
    __tablename__='packing_sessions'
    id=Column(Integer,primary_key=True); order_id=Column(ForeignKey(Order.id),unique=True); tote_id=Column(ForeignKey(Tote.id)); packer=Column(String); station=Column(String,default='PACK-STATION-01'); started=Column(DateTime,default=now); completed=Column(DateTime); camera_reference=Column(String); exceptions=Column(Text,default=''); ai_result=Column(String,default='NOT_RUN')
class Shipment(Base):
    __tablename__='shipments'
    id=Column(Integer,primary_key=True); order_id=Column(ForeignKey(Order.id),unique=True); tracking=Column(String); provider=Column(String,default='DEMO'); created=Column(DateTime,default=now)
class User(Base):
    __tablename__='users'
    id=Column(String,primary_key=True); role=Column(String)
class Audit(Base):
    __tablename__='audit_events'
    id=Column(Integer,primary_key=True); created=Column(DateTime,default=now); actor=Column(String); action=Column(String); reference=Column(String); notes=Column(Text)
class ExceptionEvent(Base):
    __tablename__='exceptions'
    id=Column(Integer,primary_key=True); created=Column(DateTime,default=now); kind=Column(String); reference=Column(String); message=Column(Text); resolved=Column(Boolean,default=False)
