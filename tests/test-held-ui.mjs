import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";
import { METRIC_KEYS, buildView, validateWeights } from "../engine/rank-filter-engine.mjs";

const source=readFileSync(new URL("../web/app.js",import.meta.url),"utf8")
  .replace(/^import\s*\{[\s\S]*?\}\s*from\s*"\.\/rank-filter-engine\.mjs";\s*/,"")
  .replace(/loadData\(\);\s*$/,"");

function harness(records){
  const nodes=new Map();
  const element=()=>({innerHTML:"",textContent:"",dataset:{},classList:{add(){},remove(){},toggle(){}},addEventListener(){},querySelector:q=>node(q),querySelectorAll:()=>[]});
  const node=q=>{if(!nodes.has(q))nodes.set(q,element());return nodes.get(q);};
  const ctx=vm.createContext({METRIC_KEYS,buildView,validateWeights,console,
    localStorage:{getItem:()=>null,setItem(){}},document:{querySelector:node,querySelectorAll:()=>[]},
    window:{addEventListener(){},scrollTo(){}},history:{state:{usv2:"tab"}},
    records,config:{metrics:METRIC_KEYS.map(key=>({key,label:key,unit:"%",source:"Source"}))}
  });
  vm.runInContext(source,ctx);
  vm.runInContext('app.records=records; app.config=config; app.appliedFilters=makeFilters(); app.draftFilters=makeFilters();',ctx);
  return {run:code=>vm.runInContext(code,ctx),nodes};
}

function row(ticker="HELD"){
  return {ticker,company:"Example",numericCount:9,lastSuccessfulRefreshAt:"2026-09-28T10:00:00Z",lastAttemptAt:"2026-10-03T01:00:00Z",metrics:Object.fromEntries(METRIC_KEYS.map(key=>[key,{status:"NUMERIC",value:12,source:"Source",updatedAt:"2026-09-28T10:00:00Z"}]))};
}
function heldRow(){
  return {...row(),refreshHold:{reason:"COVERAGE_BELOW_8_OF_9",attemptedAt:"2026-10-03T01:00:00Z",firstHeldAt:"2026-10-02T01:00:00Z",candidateNumericCount:7,minimumNumericCount:8,regressedMetrics:METRIC_KEYS.slice(0,2).map(key=>({key,previousStatus:"NUMERIC",observedStatus:"N/A",observedValue:null,observedAt:"2026-10-03T01:00:00Z",source:"Source"})),collectionErrors:[]}};
}

test("held row lists the hold, preserved verification time, attempt, and unavailable metrics",()=>{
  const h=harness([heldRow()]);
  const html=h.run("stockRow(app.records[0],0)");
  assert.match(html,/갱신 보류 · 보관값/);
  assert.match(html,/마지막 검증/);
  assert.match(html,/최근 시도/);
  assert.ok(html.includes(h.run("fmtDate(app.records[0].lastSuccessfulRefreshAt)")));
  assert.ok(html.includes(h.run("fmtDate(app.records[0].lastAttemptAt)")));
  assert.match(html,/N\/A 미해결 지표: Revenue_TTM_YoY_Pct, Gross_Margin_TTM_Pct/);
});

test("detail labels every preserved metric and identifies failed metrics separately",()=>{
  const h=harness([heldRow()]);
  h.run("renderDetail(app.records[0])");
  const html=h.nodes.get("#detailView").innerHTML;
  assert.match(html,/최근 수집 7\/9 · 최소 8\/9 미달/);
  assert.equal((html.match(/class="metric-hold-label"/g)||[]).length,9);
  assert.equal((html.match(/class="metric-regression"/g)||[]).length,2);
  assert.equal((html.match(/<b>12%<\/b>/g)||[]).length,9);
  assert.match(html,/N\/A 확인/);
});

test("unresolved recovery does not claim coverage below threshold",()=>{
  const record=heldRow();
  record.refreshHold.reason="PREVIOUS_COVERAGE_HOLD_UNRESOLVED";
  record.refreshHold.candidateNumericCount=9;
  const h=harness([record]);
  const html=h.run("holdDetail(app.records[0])");
  assert.match(html,/복구를 확인하지 못했습니다/);
  assert.doesNotMatch(html,/9\/9 · 최소 8\/9 미달/);
});

test("overview counts current held state and avoids unconditional health claim",()=>{
  const h=harness([heldRow(),row("FRESH")]);
  h.run('app.lastRefresh={heldRecordCount:0}; renderRanking(); renderData();');
  assert.match(h.nodes.get("#rankingView").innerHTML,/갱신 보류 1종목/);
  assert.match(h.nodes.get("#dataView").innerHTML,/갱신 보류 1종목/);
  assert.match(h.nodes.get("#dataView").innerHTML,/보관값 포함/);
  assert.doesNotMatch(h.nodes.get("#dataView").innerHTML,/데이터 정상 운영 중/);
});

test("recovery removes held UI and legacy rows remain compatible",()=>{
  const h=harness([heldRow()]);
  h.run("delete app.records[0].refreshHold");
  assert.equal(h.run("holdOverview()"),"");
  assert.equal(h.run("holdDetail(app.records[0])"),"");
  assert.doesNotMatch(h.run("stockRow(app.records[0],0)"),/갱신 보류|hold-badge|hold-row-note/);
  h.run("renderDetail(app.records[0])");
  assert.doesNotMatch(h.nodes.get("#detailView").innerHTML,/metric-hold-label|metric-regression/);
});

test("hold metadata changes neither rank, score, filters, nor stored metric values",()=>{
  const records=[row("A"),row("B")];
  records[1].metrics.Revenue_TTM_YoY_Pct.value=15;
  const original=structuredClone(records);
  const base=buildView(records);
  records[0].refreshHold=heldRow().refreshHold;
  const held=buildView(records);
  assert.deepEqual(held.rows.map(r=>[r.ticker,r.rank,r.quantitativeScore]),base.rows.map(r=>[r.ticker,r.rank,r.quantitativeScore]));
  const h=harness(records);
  h.run("renderRanking(); renderDetail(app.records[0]); renderData();");
  assert.deepEqual(records.map(r=>r.metrics),original.map(r=>r.metrics));
  assert.deepEqual(records.map(r=>r.lastSuccessfulRefreshAt),original.map(r=>r.lastSuccessfulRefreshAt));
});

test("held data is escaped before insertion into markup",()=>{
  const record=heldRow();
  record.refreshHold.regressedMetrics[0].key='<img src=x onerror="alert(1)">';
  record.refreshHold.candidateNumericCount="<script>bad</script>";
  const h=harness([record]);
  const html=h.run("holdDetail(app.records[0])");
  assert.doesNotMatch(html,/<img|<script>/);
  assert.match(html,/&lt;img/);
  assert.match(html,/&lt;script&gt;/);
});
