from decimal import Decimal
import math
import pytest
from research_lab.momentum_boundary import boundary_sign, positions

@pytest.mark.parametrize('end,expected',[
 ('100',0),('100.0000000001',0),('99.9999999999',0),
 ('100.00000000010001',1),('99.99999999989999',-1),
 ('100.00000000005',0),('99.99999999995',0),('101',1),('99',-1)])
def test_inclusive_boundary(end,expected):
 assert boundary_sign('100',end)==expected
 assert boundary_sign(Decimal('100')*1000,Decimal(end)*1000)==expected

@pytest.mark.parametrize('value',['0','-1','NaN','Infinity','bad'])
def test_invalid(value):
 with pytest.raises(ValueError):boundary_sign('100',value)

def test_round_trip_and_causal_alignment():
 p=['100','110','95','108','99','100','103','90','110']
 x=positions(p)
 assert all(math.isnan(v) for v in x[:6])
 assert x[6]==0  # round trip, irrespective of intermediate log rounding
 assert x[7]==-1 # end 103 versus start 110
 assert positions(p[:7])[6]==x[6]
 assert positions(p[:6]+['999','888','777'])[6]==x[6]
 assert positions(['100']*20)[6:]==[0.0]*14
