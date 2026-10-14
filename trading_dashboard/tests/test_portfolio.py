import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from portfolio import *

def test_files():
    data=Path(__file__).resolve().parents[1]/'data'
    universe=read_rankings(data/'WLS_Candidate_Shortlist_1_enriched_yahoo_enriched.xlsx')
    original,cap=read_starting_portfolio(data/'Starting Portfolio.xlsx')
    assert len(universe)==9105
    assert len(original)==20 and abs(original.Weight.sum()-1)<1e-8
    assert cap==1000000
    enriched=enrich_holdings(original,universe)
    assert enriched.loc[enriched.Ticker=='ASB.WA','Sector'].iloc[0]=='Technology'
    assert enriched.loc[enriched.Ticker=='ASB.WA','Country'].iloc[0]=='Poland'
    assert abs(stress(enriched,'Ticker','ASB.WA',-.3)-(-.024))<1e-8
    loaded,_=read_starting_portfolio(__import__('io').BytesIO(export_portfolio(enriched,cap)))
    assert len(loaded)==20 and abs(loaded.Weight.sum()-1)<1e-8

def test_weight():
    w={'A':.6,'B':.3,'C':.1}
    r=set_weight(w,'D',.2)
    assert abs(sum(r.values())-1)<1e-8
    assert abs(r['A']-.48)<1e-8
    assert abs(set_weight(r,'B',.25)['B']-.25)<1e-8

if __name__=='__main__':
    test_files();test_weight();print('All offline tests passed')

def test_remove_holdings():
    weights={'A':0.5,'B':0.3,'C':0.2}
    result=remove_holdings(weights,['B'])
    assert set(result)=={'A','C'}
    assert abs(result['A']-5/7)<1e-9
    assert abs(result['C']-2/7)<1e-9
    assert abs(sum(result.values())-1)<1e-9
    assert remove_holdings({'A':0,'B':0},['A'])=={'B':1.0}
    try: remove_holdings(weights,['A','B','C'])
    except ValueError: pass
    else: raise AssertionError('Expected ValueError when deleting all holdings')
