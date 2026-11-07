"""Source-bound calculator; graph digest is supplied by a trusted controller."""
import ast,hashlib,json,re,sys
from pathlib import Path
from decimal import Decimal,localcontext
EXPECTED_GRAPH_SHA=None
SCALES={'USD':Decimal(1),'USD_thousands':Decimal(1000),'USD_millions':Decimal(1000000)}
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def cell_value(root,node):
 f=node['source_file']
 if Path(f).name!=f:raise ValueError('unsafe_source_path')
 p=Path(root)/f
 if digest(p)!=node['source_sha256']:raise ValueError('source_hash_mismatch')
 lines=[s.split(':',1)[1] for s in p.read_text().splitlines() if s.startswith('L'+str(node['line'])+':')]
 if len(lines)!=1:raise ValueError('source_line_ambiguous_or_missing')
 text=lines[0].replace('|',' ')
 tokens=list(re.finditer(r'(\()?\s*([+-]?\d[\d,]*(?:\.\d+)?)\s*(\))?',text))
 index=node['numeric_index']
 if type(index) is not int or not 0<=index<len(tokens):raise ValueError('source_cell_missing')
 m=tokens[index];v=Decimal(m[2].replace(',',''))
 if bool(m[1])!=bool(m[3]):raise ValueError('unbalanced_source_sign')
 if m[1]:v=-v
 if str(v)!=node['reviewed_value']:raise ValueError('reviewed_cell_mismatch')
 return v

def compute_bound(items,root,expected_graph_sha=None):
 root=Path(root);pin=expected_graph_sha or EXPECTED_GRAPH_SHA
 if not pin or digest(root/'lineage-graph.json')!=pin:raise ValueError('graph_digest_mismatch')
 graph=json.loads((root/'lineage-graph.json').read_text());nodes=graph['nodes'];result={}
 if not isinstance(items,dict) or not items or len(items)>30:raise ValueError('invalid_request')
 for field,request in items.items():
  if request!={'plan_id':field}:raise ValueError('literal_operands_or_formula_override_forbidden')
  plan=graph['plans'].get(field)
  if plan is None:raise ValueError('unbound_plan')
  if plan['authority']!='controller_reviewed_calculation' or graph['execution_allowed'] is not False:raise ValueError('invalid_authority')
  bound={};receipts=[]
  for alias,node_id in plan['operands'].items():
   n=nodes[node_id]
   if n['kind']!='source_observation' or n['issuer']!=plan['issuer'] or n['source_unit'] not in SCALES:raise ValueError('invalid_operand_node')
   if not any(e=={'from':node_id,'to':plan['node_id'],'relation':'operand_of','role':alias} for e in graph['edges']):raise ValueError('missing_graph_edge')
   if any(n.get(k)!=v for k,v in plan['operand_contracts'][alias].items()):raise ValueError('operand_semantic_mismatch')
   v=cell_value(root,n);bound[alias]=v*SCALES[n['source_unit']]
   receipts.append(dict(node_id=node_id,role=alias,source_file=n['source_file'],source_sha256=n['source_sha256'],line=n['line'],numeric_index=n['numeric_index'],raw_value=str(v),source_unit=n['source_unit'],normalized_value=str(bound[alias]),metric=n['metric'],period=n['period'],vintage=n['vintage'],canonical_assertion=n['canonical_assertion']))
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
   ctx.prec=40;value=visit(tree.body)
   if not value.is_finite():raise ValueError('nonfinite')
  result[field]=dict(value=str(value),unit=plan['unit'],plan_id=field,formula=plan['formula'],graph_sha256=pin,calculation_node=plan['node_id'],operand_lineage=receipts,graph_authority=graph['authority'],canonical_graph_status=graph['canonical_graph_status'])
 return result
if __name__=='__main__':print(json.dumps(compute_bound(json.loads(sys.argv[1]),Path.cwd()),allow_nan=False))
