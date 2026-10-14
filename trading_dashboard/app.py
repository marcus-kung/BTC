from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.express as px
from portfolio import (read_rankings,read_starting_portfolio,enrich_holdings,set_weight,
    normalize_weights,remove_holdings,breakdown,weighted_metric,stress,export_portfolio)

st.set_page_config(page_title='BTC Portfolio Construction',layout='wide')
BASE=Path(__file__).parent
# Prefer the stable output filename written by yahoo_enrichment/enrich_yahoo.py.
# Supports running the app from any current working directory.
BTC_ROOT = BASE.parent
UNIVERSE_CANDIDATES = [
    BTC_ROOT / 'yahoo_enrichment' / 'output' / 'stock_metadata.xlsx',
    BASE / 'data' / 'stock_metadata.xlsx',
    BASE / 'data' / 'WLS_Candidate_Shortlist_1_enriched_yahoo_enriched.xlsx',
]
PORTFOLIO_CANDIDATES = [
    BASE / 'data' / 'Starting Portfolio.xlsx',
    BTC_ROOT / 'data' / 'Starting Portfolio.xlsx',
    BTC_ROOT / 'yahoo_enrichment' / 'Starting Portfolio.xlsx',
]

def first_existing(candidates):
    return next((p for p in candidates if p.is_file()), None)

DEFAULT_UNIVERSE = first_existing(UNIVERSE_CANDIDATES)
DEFAULT_PORTFOLIO = first_existing(PORTFOLIO_CANDIDATES)

@st.cache_data(show_spinner='Reading rankings workbook...')
def load_universe(file_bytes):return read_rankings(__import__('io').BytesIO(file_bytes))

@st.cache_data(show_spinner='Reading portfolio workbook...')
def load_portfolio(file_bytes):return read_starting_portfolio(__import__('io').BytesIO(file_bytes))

st.title('Bloomberg Trading Challenge | Portfolio & Risk')
st.caption('Offline analysis based on processed WLS rankings and imported portfolio allocations. No Yahoo Finance requests.')
with st.sidebar:
    st.header('Inputs')
    universe_upload=st.file_uploader('Enriched WLS rankings workbook',type=['xlsx'],key='universe')
    port_upload=st.file_uploader('Starting/current portfolio workbook',type=['xlsx'],key='portfolio')
    st.caption('Default universe: yahoo_enrichment/output/stock_metadata.xlsx. Upload a workbook to override it.')
    st.divider()
    st.caption('Changing an uploaded portfolio replaces the current selection; otherwise slider changes remain in this browser session.')

if universe_upload:
    universe_bytes = universe_upload.getvalue()
    universe_source = f'Uploaded: {universe_upload.name}'
elif DEFAULT_UNIVERSE:
    universe_bytes = DEFAULT_UNIVERSE.read_bytes()
    universe_source = str(DEFAULT_UNIVERSE.relative_to(BTC_ROOT)) if DEFAULT_UNIVERSE.is_relative_to(BTC_ROOT) else str(DEFAULT_UNIVERSE)
else:
    st.error('No stock metadata workbook found. Run yahoo_enrichment/enrich_yahoo.py to generate '
             'yahoo_enrichment/output/stock_metadata.xlsx, or upload a workbook using the sidebar.')
    st.stop()

if port_upload:
    portfolio_bytes = port_upload.getvalue()
    portfolio_source = f'Uploaded: {port_upload.name}'
elif DEFAULT_PORTFOLIO:
    portfolio_bytes = DEFAULT_PORTFOLIO.read_bytes()
    portfolio_source = str(DEFAULT_PORTFOLIO.relative_to(BTC_ROOT)) if DEFAULT_PORTFOLIO.is_relative_to(BTC_ROOT) else str(DEFAULT_PORTFOLIO)
else:
    st.error('No starting portfolio workbook found. Upload a portfolio Excel file using the sidebar.')
    st.stop()
st.caption(f'Stock metadata: `{universe_source}`  |  Starting portfolio: `{portfolio_source}`')
try:
    universe=load_universe(universe_bytes)
    starting,import_capital=load_portfolio(portfolio_bytes)
except Exception as e:
    st.error(f'Unable to read workbook: {e}');st.stop()

source_key=(hash(universe_bytes),hash(portfolio_bytes))
if st.session_state.get('source_key')!=source_key:
    st.session_state.source_key=source_key
    st.session_state.weights=dict(zip(starting['Ticker'],starting['Weight']))
    st.session_state.import_info=starting.set_index('Ticker')[['Name','Country','Bloomberg Ticker']].to_dict('index')
    st.session_state.capital=float(import_capital)
    st.session_state.widget_version=st.session_state.get('widget_version',0)+1

left,right=st.columns([1,1])
with left:
    st.metric('Stocks in WLS ranked universe',f'{len(universe):,}')
with right:
    st.number_input('Portfolio notional (same currency as imported portfolio)',min_value=0.,step=10000.,key='capital')

weights=st.session_state.weights
sum_w=sum(weights.values())
if abs(sum_w-1)>1e-6:
    st.warning(f'Imported weights sum to {sum_w:.2%}, not 100%. The dashboard shows the original weights until you normalise or edit a position.')
    if st.button('Normalise portfolio weights to 100%'):
        st.session_state.weights=normalize_weights(weights)
        st.rerun()

selected=set(weights)
unknown=[t for t in selected if t not in set(universe.Ticker)]
if unknown:st.warning('Missing from WLS rankings (retained using imported metadata): '+', '.join(sorted(unknown)))

st.subheader('Find and add a WLS stock')
term=st.text_input('Search by Yahoo ticker or company name',placeholder='e.g. MU or Micron').strip()
if term:
    match=universe[universe['Ticker'].str.contains(term,case=False,regex=False,na=False)|universe['Name'].astype(str).str.contains(term,case=False,regex=False,na=False)].head(60)
else:
    match=universe.nsmallest(40,'Rank')
choice_labels={f"{r.Ticker}  |  {str(r.Name)[:50]}  |  rank {r.Rank if pd.notna(r.Rank) else 'N/A'}":r.Ticker for r in match.itertuples()}
if choice_labels:
    selected_label=st.selectbox('Matching WLS stocks',list(choice_labels),index=None,placeholder='Select a stock to add')
    if st.button('Add selected stock (initial weight 0%)',disabled=not selected_label):
        ticker=choice_labels[selected_label]
        if ticker in weights:st.info(f'{ticker} is already in your portfolio. Use its slider below.')
        else:
            st.session_state.weights[ticker]=0.
            st.rerun()
else:st.info('No matching WLS tickers in the uploaded rankings workbook.')

st.divider()
st.subheader('Position weights')
st.caption('Each slider sets the selected position weight. Remaining capital is automatically redistributed **proportionally across the other holdings**. Adding a stock at 0% leaves existing allocations unchanged.')
# Edit positions one at a time to avoid slider/session-value conflict.
position=st.selectbox('Position to resize',sorted(weights),format_func=lambda t:f"{t} — {universe.set_index('Ticker').at[t,'Name'] if t in set(universe.Ticker) else st.session_state.import_info.get(t,{}).get('Name',t)}")
current=float(weights[position])
new_w=st.slider('Target allocation',min_value=0.0,max_value=100.0,value=float(round(current*100,3)),step=0.25,key=f'weight_{position}_{st.session_state.widget_version}')
buttons=st.columns([1,1,3])
with buttons[0]:
    if st.button('Apply weighting',type='primary'):
        st.session_state.weights=set_weight(st.session_state.weights,position,new_w/100)
        st.session_state.widget_version+=1
        st.rerun()
with buttons[1]:
    if st.button('Remove holding',disabled=len(weights)<2):
        st.session_state.weights=remove_holdings(st.session_state.weights,[position])
        st.session_state.widget_version+=1
        st.rerun()
with buttons[2]:
    if st.button('Reset to uploaded portfolio'):
        st.session_state.weights=dict(zip(starting['Ticker'],starting['Weight']))
        st.session_state.widget_version+=1
        st.rerun()

st.markdown('#### Delete multiple holdings')
st.caption('Choose one or more existing positions to remove. Remaining holdings are reweighted proportionally to 100%.')
to_delete=st.multiselect('Holdings to delete', sorted(st.session_state.weights),
                         format_func=lambda t: f"{t} ({st.session_state.weights[t]:.2%})")
if st.button('Delete selected holdings', disabled=not to_delete or len(to_delete)>=len(st.session_state.weights)):
    st.session_state.weights=remove_holdings(st.session_state.weights,to_delete)
    st.session_state.widget_version+=1
    st.rerun()
if to_delete and len(to_delete)==len(st.session_state.weights):
    st.warning('You must retain at least one holding. To replace the whole portfolio, import another workbook.')

hold=pd.DataFrame({'Ticker':list(st.session_state.weights),'Weight':list(st.session_state.weights.values())})
for col in ['Name','Country','Bloomberg Ticker']:
    hold[col]=hold.Ticker.map({k:v.get(col) for k,v in st.session_state.import_info.items()})
hold=enrich_holdings(hold,universe)
hold['Value']=hold['Weight']*st.session_state.capital
hold=hold.sort_values('Weight',ascending=False).reset_index(drop=True)

m1,m2,m3,m4=st.columns(4)
m1.metric('Holdings',len(hold));m2.metric('Total allocated',f"{hold.Weight.sum():.2%}")
m3.metric('Largest position',f"{hold.Weight.max():.2%}")
m4.metric('Effective positions',f"{1/(hold.Weight.pow(2).sum()):.2f}" if hold.Weight.pow(2).sum()>0 else 'N/A')
show_cols=['Ticker','Name','Weight','Value','Country','Sector','Industry','Score','Rank','Beta_6M']
display_hold=hold[show_cols].copy()
display_hold['Weight']=display_hold['Weight']*100
st.dataframe(display_hold,use_container_width=True,hide_index=True,column_config={
    'Weight':st.column_config.NumberColumn(format='%.2f%%',help='Percent allocation'),
    'Value':st.column_config.NumberColumn(format='%.2f')})

st.subheader('Allocation breakdown')
tabs=st.tabs(['Positions','Sectors','Countries','Industries'])
for tab,field in zip(tabs,['Ticker','Sector','Country','Industry']):
    with tab:
        d=breakdown(hold,field)
        d['Weight %']=d.Weight*100
        chart=px.bar(d.head(45),x=field,y='Weight %',text='Weight %',title=f'{field} exposure')
        chart.update_traces(texttemplate='%{text:.1f}%',textposition='outside')
        chart.update_layout(yaxis_title='% of notional',xaxis_title=field)
        st.plotly_chart(chart,use_container_width=True)
        st.dataframe(d[[field,'Weight %']].style.format({'Weight %':'{:.2f}%'}),use_container_width=True,hide_index=True)

st.subheader('Portfolio characteristics from existing screening metrics')
metric_fields={'Beta to WLS (approx.)':'Beta_6M','12–1 momentum (weighted average)':'Momentum_12_1','6M stock volatility (weighted average; not portfolio vol.)':'Volatility_6M','Stock drawdown (weighted average; not portfolio drawdown)':'Max_Drawdown','Screening score (weighted average)':'Score'}
cols=st.columns(3)
for ix,(label,field) in enumerate(metric_fields.items()):
    result,coverage=weighted_metric(hold,field)
    cols[ix%3].metric(label,f'{result:.3f}' if pd.notna(result) else 'N/A',help=f'Only {coverage:.1%} of portfolio weights have this metric.')
missing_country=hold.loc[hold.Country.eq('Unknown'),'Weight'].sum()
if missing_country>0:st.warning(f'{missing_country:.1%} of the portfolio has unknown country metadata. Country exposure may be incomplete; use an import with country labels or update your workbook.')

st.subheader('Hypothetical stress tests')
a,b=st.columns(2)
with a:
    shock_pct=st.slider('Shock magnitude (%)',min_value=-90,max_value=0,value=-30,step=5)
with b:
    stress_field=st.selectbox('Apply shock by',['Ticker','Sector','Country','Industry'])
options=sorted(hold[stress_field].dropna().unique().tolist())
target=st.selectbox('Affected holding/group',options)
impact=stress(hold,stress_field,target,shock_pct/100)
st.metric('Estimated portfolio impact',f'{impact:.2%}',delta=f'{impact*st.session_state.capital:,.0f} notional change',delta_color='normal')
st.caption('Static, instantaneous shock: unchanged prices assumed for all unaffected stocks; not a historical VaR, return forecast or covariance stress model.')

st.subheader('Export current allocation')
st.download_button('Download portfolio and exposure workbook',data=export_portfolio(hold,st.session_state.capital),file_name='BTC_Current_Portfolio.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',type='primary')
st.caption('Exports can be uploaded again as the current portfolio. Existing allocation workbook values remain unchanged unless you download a new file.')
