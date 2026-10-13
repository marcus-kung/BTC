"""Pure offline calculations and workbook adapters."""
from __future__ import annotations
from pathlib import Path
import io
import pandas as pd
import numpy as np


def read_rankings(source):
    full = pd.read_excel(source, sheet_name='Full Rankings', engine='openpyxl')
    full.columns = full.columns.astype(str).str.strip()
    if 'Ticker' not in full: raise ValueError('Full Rankings must contain Ticker.')
    full['Ticker'] = full['Ticker'].astype('string').str.strip().str.upper()
    full = full.dropna(subset=['Ticker']).drop_duplicates('Ticker').copy()
    for c in ['Name','Sector','Industry']:
        if c not in full: full[c] = pd.NA
    if 'Country' not in full: full['Country'] = pd.NA
    try:
        top = pd.read_excel(source, sheet_name='Top 30 Candidates', engine='openpyxl')
        top['Ticker'] = top['Ticker'].astype('string').str.strip().str.upper()
        if 'Country' in top:
            by_ticker=top.dropna(subset=['Ticker']).drop_duplicates('Ticker').set_index('Ticker')['Country']
            full['Country']=full['Country'].fillna(full['Ticker'].map(by_ticker))
        for c in ['Name','Sector','Industry']:
            if c in top:
                by_ticker=top.dropna(subset=['Ticker']).drop_duplicates('Ticker').set_index('Ticker')[c]
                full[c]=full[c].fillna(full['Ticker'].map(by_ticker))
    except ValueError: pass
    full['Name']=full['Name'].fillna(full['Ticker'])
    for c in ['Sector','Industry','Country']: full[c]=full[c].fillna('Unknown').replace('', 'Unknown')
    for c in ['Score','Rank','Beta_6M','Momentum_12_1','Volatility_6M','Max_Drawdown','Recent_Return_2M']:
        if c not in full:full[c]=np.nan
        full[c]=pd.to_numeric(full[c],errors='coerce')
    return full


def read_starting_portfolio(source):
    """Accept the supplied unlabelled layout, or a dashboard export."""
    raw=pd.read_excel(source, sheet_name=0, header=None, engine='openpyxl')
    if raw.empty:raise ValueError('Portfolio sheet is empty')
    capital=pd.to_numeric(pd.Series([raw.iat[0,1] if raw.shape[1]>1 else None]),errors='coerce').iloc[0]
    if not np.isfinite(capital):capital=1_000_000.
    # Detect a header anywhere in first 12 lines (original workbook uses row 3)
    hdr=None
    for i in range(min(12,len(raw))):
        vals=[str(x).strip().lower() for x in raw.iloc[i] if pd.notna(x)]
        if any('ticker' in v for v in vals) and any('name' in v for v in vals):hdr=i;break
    if hdr is None:raise ValueError('Could not find a ticker/name header row')
    header=[str(v).strip() if pd.notna(v) else '' for v in raw.iloc[hdr]]
    body=raw.iloc[hdr+1:].copy();body.columns=header
    ticker_col=next((c for c in body if c.lower() in ('yahoo finance ticker','ticker','yahoo ticker')),None)
    if ticker_col is None:raise ValueError('Expected Yahoo Finance Ticker or Ticker column')
    # Original workbook has anonymous Country, Weight and Value immediately after Name
    if 'Weight' in body.columns:
        wc='Weight'; cc='Country' if 'Country' in body else None
    else:
        name_pos=header.index('Name') if 'Name' in header else 3
        cc=header[name_pos+1] if name_pos+1<len(header) else None
        wc=header[name_pos+2] if name_pos+2<len(header) else None
        # Duplicate blank headers: use integer locations to avoid ambiguous selection
        work=pd.DataFrame({'Ticker':body[ticker_col], 'Name':body['Name'] if 'Name' in body else None,
             'Country':raw.iloc[hdr+1:,name_pos+1].to_numpy() if name_pos+1<raw.shape[1] else None,
             'Weight':raw.iloc[hdr+1:,name_pos+2].to_numpy() if name_pos+2<raw.shape[1] else None,
             'Value':raw.iloc[hdr+1:,name_pos+3].to_numpy() if name_pos+3<raw.shape[1] else None})
        work['Bloomberg Ticker']=body['Bloomberg Ticker'].to_numpy() if 'Bloomberg Ticker' in body else ''
        return _clean_portfolio(work),float(capital)
    work=pd.DataFrame({'Ticker':body[ticker_col], 'Name':body['Name'] if 'Name' in body else None,
        'Country':body[cc] if cc else None,'Weight':body[wc],
        'Value':body['Value'] if 'Value' in body else None,
        'Bloomberg Ticker':body['Bloomberg Ticker'] if 'Bloomberg Ticker' in body else ''})
    # A dashboard export carries capital as a distinct column
    if 'Portfolio Capital' in body:
        detected=pd.to_numeric(body['Portfolio Capital'],errors='coerce').dropna()
        if len(detected): capital=float(detected.iloc[0])
    return _clean_portfolio(work),float(capital)


def _clean_portfolio(df):
    df=df.copy()
    df['Ticker']=df['Ticker'].astype('string').str.strip().str.upper()
    df=df.dropna(subset=['Ticker'])
    df=df[~df['Ticker'].isin(['','NAN','NONE','TOTAL'])]
    for c in ['Weight','Value']:df[c]=pd.to_numeric(df[c],errors='coerce')
    if df['Weight'].isna().all() and df['Value'].notna().any():
        df['Weight']=df['Value']/df['Value'].sum()
    if df['Weight'].dropna().gt(1).any():
        # percent format from an external spreadsheet, e.g. 8 means 8%
        if df['Weight'].dropna().between(0,100).all():df['Weight']/=100
    df['Weight']=df['Weight'].fillna(0)
    if df['Ticker'].duplicated().any():
        df=df.groupby('Ticker',as_index=False).agg({'Name':'first','Country':'first','Weight':'sum','Value':'sum','Bloomberg Ticker':'first'})
    return df.reset_index(drop=True)


def enrich_holdings(holdings,universe):
    lookup=universe.set_index('Ticker')
    out=holdings.copy()
    for c in ['Name','Sector','Industry','Country','Score','Rank','Beta_6M','Momentum_12_1','Volatility_6M','Max_Drawdown']:
        mapped=out['Ticker'].map(lookup[c]) if c in lookup else pd.Series(np.nan,index=out.index)
        if c in ('Name','Country') and c in out:
            out[c]=out[c].replace('',np.nan).fillna(mapped)
        else:out[c]=mapped
    for c in ['Name','Sector','Industry','Country']:out[c]=out[c].fillna('Unknown')
    return out


def set_weight(weights:dict[str,float],ticker:str,target:float)->dict[str,float]:
    """Set one weight and redistribute residual proportional to other positions."""
    target=max(0.,min(1.,float(target)))
    w={k:max(0.,float(v)) for k,v in weights.items()}
    if ticker not in w:w[ticker]=0.
    others=[k for k in w if k!=ticker]
    old_sum=sum(w[k] for k in others)
    if not others:
        w[ticker]=1.
        return w
    if old_sum>0:
        for k in others:w[k]=w[k]/old_sum*(1-target)
    else:
        for k in others:w[k]=(1-target)/len(others)
    w[ticker]=target
    return w


def remove_holdings(weights:dict[str,float], tickers)->dict[str,float]:
    """Delete holdings, proportionally reweight remaining holdings to 100%."""
    remove=set(tickers)
    kept={ticker:float(weight) for ticker,weight in weights.items() if ticker not in remove}
    if not kept:
        raise ValueError('At least one holding must remain in the portfolio.')
    result=normalize_weights(kept)
    if sum(result.values())<=0:
        equal=1/len(result)
        result={ticker:equal for ticker in result}
    return result


def normalize_weights(weights:dict[str,float])->dict[str,float]:
    denom=sum(max(0.,float(v)) for v in weights.values())
    if denom<=0:return weights.copy()
    return {k:max(0.,float(v))/denom for k,v in weights.items()}


def breakdown(holdings,category):
    return (holdings.groupby(category,dropna=False)['Weight'].sum().sort_values(ascending=False).rename('Weight').reset_index())


def weighted_metric(holdings,col):
    vals=pd.to_numeric(holdings[col],errors='coerce');w=holdings['Weight'].where(vals.notna(),0)
    return (float((vals.fillna(0)*w).sum()/w.sum()),float(w.sum())) if w.sum()>0 else (np.nan,0.)


def stress(holdings, column, name, shock):
    mask=holdings[column].eq(name)
    return float(holdings.loc[mask,'Weight'].sum()*shock)


def export_portfolio(holdings,capital):
    df=holdings.copy()
    df['Value']=df['Weight']*capital
    df['Portfolio Capital']=capital
    buf=io.BytesIO()
    with pd.ExcelWriter(buf,engine='openpyxl') as writer:
        cols=['Ticker','Name','Bloomberg Ticker','Country','Sector','Industry','Weight','Value','Portfolio Capital','Score','Rank','Beta_6M','Momentum_12_1','Volatility_6M','Max_Drawdown']
        df[[c for c in cols if c in df]].to_excel(writer,index=False,sheet_name='Portfolio')
        for field in ['Sector','Country','Industry']:
            breakdown(df,field).to_excel(writer,index=False,sheet_name=field+' Exposure')
        from openpyxl.styles import Font,PatternFill
        for ws in writer.book.worksheets:
            ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
            for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='16324A')
            for col in ws.columns:
                letter=col[0].column_letter
                ws.column_dimensions[letter].width=min(40,max(13,max(len(str(c.value or '')) for c in list(col)[:200])+2))
    return buf.getvalue()
