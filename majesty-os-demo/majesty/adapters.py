"""Extension contracts. No live integrations are configured or called."""
from typing import Protocol
from io import BytesIO
class MarketplaceAdapter(Protocol):
    def fetch_orders(self) -> list[dict]: ...
    def update_tracking(self, order_id: str, tracking: str) -> None: ...
class ShippingAdapter(Protocol):
    def tracking(self, order_id: int) -> str: ...
    def label_pdf(self, tracking: str) -> bytes: ...
class CameraAdapter(Protocol):
    def start(self, session_id: int) -> str: ...
    def stop(self, reference: str) -> None: ...
class PackingVerifier(Protocol):
    def compare(self, expected: list[dict], observations: list[dict]) -> dict: ...
class DemoMarketplace:
    def fetch_orders(self):
        return [{'source':'TIKTOK','external':'TT10001','lines':[{'key':'tt-vanaco-30','title':'Vanaco 30ML','qty':2},{'key':'MJS-FR-0002-RO-50','title':'Rouge Extrait 50 mL','qty':1}]}, {'source':'SHOPIFY','external':'SH10002','lines':[{'key':'unknown-laytown','title':'Laytown 50 mL','qty':1}]}]
    def update_tracking(self, order_id, tracking): return {'demo':True,'sent':False}
class DemoShipping:
    def tracking(self,order_id): return f'DEMO-NOT-VALID-{order_id:08d}'
    def label_pdf(self,tracking):
        from reportlab.pdfgen.canvas import Canvas
        out=BytesIO(); c=Canvas(out,pagesize=(288,432))
        for y,text in [(390,'MAJESTY OS / DEMO'),(350,'VOID — NOT FOR SHIPPING'),(300,tracking),(240,'TEST RECIPIENT'),(215,'NO REAL ADDRESS'),(150,'NO POSTAGE / NO CARRIER')]: c.drawString(20,y,text)
        c.showPage(); c.save(); return out.getvalue()
