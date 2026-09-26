export const METRIC_KEYS = Object.freeze([
  "Revenue_TTM_YoY_Pct",
  "Gross_Margin_TTM_Pct",
  "Operating_Margin_TTM_Pct",
  "Net_Margin_TTM_Pct",
  "ROA_TTM_Pct",
  "FCF_Yield_TTM_Pct",
  "Price_Sales_TTM",
  "Shares_Change_YoY_Pct",
  "Drawdown_52W_Pct",
]);

export const DEFAULT_WEIGHTS = Object.freeze({
  Revenue_TTM_YoY_Pct: 12,
  Gross_Margin_TTM_Pct: 10,
  Operating_Margin_TTM_Pct: 12,
  Net_Margin_TTM_Pct: 10,
  ROA_TTM_Pct: 8,
  FCF_Yield_TTM_Pct: 14,
  Price_Sales_TTM: 14,
  Shares_Change_YoY_Pct: 8,
  Drawdown_52W_Pct: 12,
});

export const DEFAULT_FILTERS = Object.freeze({
  Revenue_TTM_YoY_Pct: { enabled: false, op: ">=", value: 15 },
  Gross_Margin_TTM_Pct: { enabled: false, op: ">=", value: 40 },
  Operating_Margin_TTM_Pct: { enabled: false, op: ">=", value: 15 },
  Net_Margin_TTM_Pct: { enabled: false, op: ">=", value: 10 },
  ROA_TTM_Pct: { enabled: false, op: ">=", value: 8 },
  FCF_Yield_TTM_Pct: { enabled: false, op: ">=", value: 5 },
  Price_Sales_TTM: { enabled: false, op: "<=", value: 4 },
  Shares_Change_YoY_Pct: { enabled: false, op: "<=", value: 5 },
  Drawdown_52W_Pct: { enabled: false, op: "range", min: 15, max: 60 },
});

const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
const finite=v=>typeof v==="number"&&Number.isFinite(v);
const valueOf=(record,key)=>{
  const cell=record?.metrics?.[key];
  return cell?.status==="NUMERIC"&&finite(cell.value)?cell.value:null;
};

export function validateWeights(weights){
  const keys=Object.keys(weights||{});
  if(keys.length!==METRIC_KEYS.length||METRIC_KEYS.some(k=>!keys.includes(k)))return false;
  if(METRIC_KEYS.some(k=>!finite(Number(weights[k]))||Number(weights[k])<0))return false;
  const total=METRIC_KEYS.reduce((s,k)=>s+Number(weights[k]),0);
  return Math.abs(total-100)<1e-9;
}

export function equalWeights(){
  const base=Math.floor((100/9)*10)/10; // 11.1
  const out=Object.fromEntries(METRIC_KEYS.map(k=>[k,base]));
  out[METRIC_KEYS[0]]=Number((100-base*8).toFixed(1)); // 11.2
  return out;
}

export function passesMetricFilter(value,filter){
  if(!filter?.enabled)return true;
  if(value===null)return false;
  if(filter.op===">=")return value>=Number(filter.value);
  if(filter.op==="<=")return value<=Number(filter.value);
  if(filter.op==="range")return value>=Number(filter.min)&&value<=Number(filter.max);
  return true;
}

export function applyFilters(records,filters=DEFAULT_FILTERS,minimumConnected=8){
  return (records||[]).filter(record=>{
    if(Number(record?.numericCount||0)<minimumConnected)return false;
    return METRIC_KEYS.every(key=>passesMetricFilter(valueOf(record,key),filters?.[key]));
  });
}

const DEFAULT_BOUNDS=Object.freeze({
  Revenue_TTM_YoY_Pct:[-50,100],
  Gross_Margin_TTM_Pct:[0,100],
  Operating_Margin_TTM_Pct:[-50,60],
  Net_Margin_TTM_Pct:[-50,60],
  ROA_TTM_Pct:[-30,50],
  FCF_Yield_TTM_Pct:[-20,40],
  Price_Sales_TTM:[0,20],
  Shares_Change_YoY_Pct:[-30,50],
  Drawdown_52W_Pct:[0,80],
});

const LOWER_BETTER=new Set(["Price_Sales_TTM","Shares_Change_YoY_Pct"]);
const DRAW_DOWN_KEY="Drawdown_52W_Pct";

function normalizedMetric(key,value,bounds=DEFAULT_BOUNDS){
  if(value===null)return null;
  const [lo,hi]=bounds[key];
  if(hi<=lo)return 0;
  let n=(clamp(value,lo,hi)-lo)/(hi-lo);
  if(LOWER_BETTER.has(key))n=1-n;
  if(key===DRAW_DOWN_KEY){
    // V2 treats moderate drawdown as opportunity, not "more is always better".
    // Peak score at ~35%, tapering toward 0% and 80%.
    const target=35, span=45;
    n=1-clamp(Math.abs(value-target)/span,0,1);
  }
  return n*100;
}

export function scoreRecord(record,weights=DEFAULT_WEIGHTS,bounds=DEFAULT_BOUNDS){
  if(!validateWeights(weights))throw new Error("PUBLIC_V2_WEIGHT_TOTAL_MUST_EQUAL_100");
  let weighted=0,used=0;
  for(const key of METRIC_KEYS){
    const n=normalizedMetric(key,valueOf(record,key),bounds);
    if(n===null)continue;
    const w=Number(weights[key]);
    weighted+=n*w;
    used+=w;
  }
  if(used<=0)return null;
  return Number((weighted/used).toFixed(2));
}

export function rankRecords(records,weights=DEFAULT_WEIGHTS,sortKey="score",direction="desc"){
  const dir=direction==="asc"?1:-1;
  const rows=(records||[]).map(record=>({
    ...record,
    quantitativeScore:scoreRecord(record,weights),
  }));
  rows.sort((a,b)=>{
    if(sortKey==="score"){
      const av=a.quantitativeScore??-Infinity,bv=b.quantitativeScore??-Infinity;
      if(av!==bv)return (av-bv)*dir;
    }else{
      const av=valueOf(a,sortKey),bv=valueOf(b,sortKey);
      if(av===null&&bv!==null)return 1;
      if(av!==null&&bv===null)return -1;
      if(av!==null&&bv!==null&&av!==bv)return (av-bv)*dir;
    }
    return String(a.ticker).localeCompare(String(b.ticker));
  });
  return rows.map((row,i)=>({...row,rank:i+1}));
}

export function buildView(records,{filters=DEFAULT_FILTERS,weights=DEFAULT_WEIGHTS,minimumConnected=8,sortKey="score",direction="desc"}={}){
  const filtered=applyFilters(records,filters,minimumConnected);
  const ranked=rankRecords(filtered,weights,sortKey,direction);
  return {
    totalInput:(records||[]).length,
    totalMatched:ranked.length,
    minimumConnected,
    weights,
    rows:ranked,
  };
}
