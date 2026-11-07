"""Source-bound arithmetic from a flat ledger, with no graph traversal."""
import ast,json
from pathlib import Path
from decimal import Decimal,localcontext
try:from cellcheck import cell_value,digest,SCALES
except ImportError:from .reconciliation_operands20 import cell_value,digest,SCALES
EXPECTED_LEDGER_SHA=None

def compute_flat(items,root,expected_sha=None):
 root=Path(root);pin=expected_sha or EXPECTED_LEDGER_SHA
 if not pin or digest(root/'operand-ledger.json')!=pin:raise ValueError('ledger_digest_mismatch')
 ledger=json.loads((root/'operand-ledger.json').read_text());result={}
 if not isinstance(items,dict) or not items:raise ValueError('invalid_request')
 for field,request in items.items():
  if request!={'plan_id':field}:raise ValueError('literal_operands_or_formula_override_forbidden')
  plan=ledger['plans'][field];bound={};receipts=[]
  for role,n in plan['operands'].items():
   if n['source_unit'] not in SCALES:raise ValueError('unsupported_unit')
   v=cell_value(root,n);bound[role]=v*SCALES[n['source_unit']]
   receipts.append(dict(role=role,source_file=n['source_file'],source_sha256=n['source_sha256'],line=n['line'],numeric_index=n['numeric_index'],raw_value=str(v),source_unit=n['source_unit'],normalized_value=str(bound[role]),metric=n['metric'],period=n['period'],vintage=n['vintage'],canonical_assertion=None))
  tree=ast.parse(plan['formula'],mode='eval')
  if len(list(ast.walk(tree)))>100:raise ValueError('formula_too_complex')
  def visit(n):
   if isinstance(n,ast.Name) and n.id in bound:return bound[n.id]
   if isinstance(n,ast.Constant) and type(n.value) is int and n.value==100 and plan['unit']=='percent':return Decimal(100)
   if isinstance(n,ast.BinOp):
    a,b=visit(n.left),visit(n.right)
    if isinstance(n.op,ast.Add):return a+b
    if isinstance(n.op,ast.Sub):return a-b
    if isinstance(n.op,ast.Mult):return a*b
    if isinstance(n.op,ast.Div):return a/b
   raise ValueError('unapproved_formula')
  with localcontext() as ctx:
   ctx.prec=40;v=visit(tree.body)
   if not v.is_finite():raise ValueError('nonfinite')
  result[field]=dict(value=str(v),unit=plan['unit'],plan_id=field,formula=plan['formula'],operand_lineage=receipts,ledger_sha256=pin,authority='controller_reviewed_flat_table',canonical_graph_status='unlinked')
 return result
COMPUTE=compute_flat
