import {
  METRIC_KEYS,
  buildView,
  validateWeights
} from "./rank-filter-engine.mjs";

const $ = (q,root=document)=>root.querySelector(q);
const $$ = (q,root=document)=>[...root.querySelectorAll(q)];

const views = {
  ranking: $("#rankingView"),
  filter: $("#filterView"),
  favorites: $("#favoritesView"),
  data: $("#dataView"),
  detail: $("#detailView"),
};
const nav = $("#bottomNav");
const loadingView = $("#loadingView");
const errorView = $("#errorView");
const headerSub = $("#headerSub");

const UI_DEFAULT_WEIGHTS = Object.freeze({
  Revenue_TTM_YoY_Pct: 15,
  Gross_Margin_TTM_Pct: 15,
  Operating_Margin_TTM_Pct: 10,
  Net_Margin_TTM_Pct: 10,
  ROA_TTM_Pct: 10,
  FCF_Yield_TTM_Pct: 10,
  Price_Sales_TTM: 10,
  Shares_Change_YoY_Pct: 10,
  Drawdown_52W_Pct: 10,
});

const SECTOR_ORDER = Object.freeze([
  "기술","헬스케어","금융","경기소비재","필수소비재","산업재",
  "커뮤니케이션","에너지","소재","부동산","유틸리티","기타"
]);

function normalizedSector(record){
  const raw=String(record?.sector || record?.category || "").trim();
  if(!raw) return "기타";
  const s=raw.toLowerCase();

  const rules=[
    ["기술",["technology","information technology","tech","software","semiconductor","computer","electronic technology","technology services","하드웨어","소프트웨어","반도체","기술"]],
    ["헬스케어",["healthcare","health care","medical","biotechnology","biotech","pharmaceutical","drug","헬스케어","의료","바이오","제약"]],
    ["금융",["financial","finance","bank","insurance","capital markets","asset management","금융","은행","보험"]],
    ["경기소비재",["consumer cyclical","consumer discretionary","retail","automotive","auto","travel","leisure","restaurant","경기소비재"]],
    ["필수소비재",["consumer defensive","consumer staples","food","beverage","household","tobacco","필수소비재"]],
    ["산업재",["industrials","industrial","aerospace","defense","machinery","transportation","business services","산업재"]],
    ["커뮤니케이션",["communication services","communication","telecom","media","entertainment","internet content","커뮤니케이션","통신","미디어"]],
    ["에너지",["energy","oil","gas","coal","에너지"]],
    ["소재",["basic materials","materials","chemicals","steel","metals","mining","paper","소재"]],
    ["부동산",["real estate","reit","부동산"]],
    ["유틸리티",["utilities","utility","electric","water","regulated gas","유틸리티"]]
  ];

  for(const [label,keywords] of rules){
    if(keywords.some(k=>s.includes(k))) return label;
  }
  return "기타";
}

const app = {
  records: [],
  recordMap: new Map(),
  config: null,
  lastRefresh: null,
  tab: "ranking",
  previousTab: "ranking",
  detailTicker: null,
  query: "",
  sector: "ALL",
  connected: "8",
  sortKey: "score",
  visibleRows: 120,
  favorites: new Set(JSON.parse(localStorage.getItem("usv2.favorites") || "[]")),
  appliedFilters: null,
  draftFilters: null,
  appliedWeights: {...UI_DEFAULT_WEIGHTS},
  draftWeights: {...UI_DEFAULT_WEIGHTS},
  loaded: false,
};

function deepClone(v){ return JSON.parse(JSON.stringify(v)); }
function esc(v){
  return String(v ?? "").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));
}
function n(v,d=1){
  const x=Number(v);
  return Number.isFinite(x) ? x.toLocaleString("ko-KR",{maximumFractionDigits:d}) : "—";
}
function metricValue(r,key){
  const c=r?.metrics?.[key];
  return c?.status==="NUMERIC" && Number.isFinite(Number(c.value)) ? Number(c.value) : null;
}
function metricText(r,key){
  const v=metricValue(r,key);
  if(v===null) return "N/A";
  const meta=app.config?.metrics?.find(m=>m.key===key);
  if(meta?.unit==="%") return `${n(v,1)}%`;
  if(meta?.unit==="x") return `${n(v,2)}x`;
  return n(v,2);
}
function metricLabel(key){
  return app.config?.metrics?.find(m=>m.key===key)?.label || key;
}
function fmtDate(v){
  if(!v) return "—";
  const d=new Date(v);
  if(Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleString("ko-KR",{year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"});
}
function heldRecords(){
  // Read the current state, not just the most recent batch's hold count.
  return app.records.filter(r=>r.refreshHold);
}
function heldMetrics(r){
  const metrics=r.refreshHold?.regressedMetrics;
  return Array.isArray(metrics) ? metrics : [];
}
function holdMetricText(r){
  const metrics=heldMetrics(r);
  return metrics.length ? `N/A 미해결 지표: ${metrics.map(m=>metricLabel(m.key)).join(", ")}` : "최근 수집 결과를 검증하지 못했습니다.";
}
function holdDates(r){
  return `마지막 검증 ${fmtDate(r.lastSuccessfulRefreshAt)} · 최근 시도 ${fmtDate(r.refreshHold?.attemptedAt || r.lastAttemptAt)}`;
}
function holdOverview(){
  const count=heldRecords().length;
  return count ? `<div class="refresh-notice" role="status"><strong>갱신 보류 ${count.toLocaleString()}종목 · 이전 검증값 표시 중</strong><p>수집 지표 부족 또는 복구 미확인으로 기존 지표와 검증 시각을 유지합니다. 연결 수·점수·필터에는 보관값이 포함됩니다.</p></div>` : "";
}
function holdDetail(r){
  if(!r.refreshHold) return "";
  const h=r.refreshHold;
  const reason=h.reason==="PREVIOUS_COVERAGE_HOLD_UNRESOLVED"
    ? "이전에 N/A로 확인된 지표의 복구를 확인하지 못했습니다."
    : `최근 수집 ${h.candidateNumericCount ?? "—"}/9 · 최소 ${h.minimumNumericCount ?? 8}/9 미달.`;
  return `<div class="refresh-notice" role="status">
    <strong>갱신 보류 · 이전 검증값 표시 중</strong>
    <p>${esc(reason)} 아래 지표는 이번 시도의 새 값이 아닙니다.</p>
    <p>${esc(holdDates(r))}</p>
    <p>${esc(holdMetricText(r))}</p>
  </div>`;
}
function persistFavorites(){
  localStorage.setItem("usv2.favorites",JSON.stringify([...app.favorites]));
}
function toast(msg){
  let el=$(".toast");
  if(!el){
    el=document.createElement("div");el.className="toast";document.body.appendChild(el);
  }
  el.textContent=msg;el.classList.add("show");
  clearTimeout(toast._t);toast._t=setTimeout(()=>el.classList.remove("show"),1800);
}

function makeFilters(){
  const out={};
  for(const m of app.config.metrics){
    const d=m.defaultFilter || {};
    out[m.key]= d.operator==="range"
      ? {enabled:false,op:"range",min:Number(d.min ?? 0),max:Number(d.max ?? 100)}
      : {enabled:false,op:d.operator || ">=",value:Number(d.value ?? 0)};
  }
  return out;
}

async function fetchJson(url,force=false){
  const suffix=force ? `${url.includes("?")?"&":"?"}cb=${Date.now()}` : "";
  const r=await fetch(url+suffix,{cache:force?"no-store":"default"});
  if(!r.ok) throw new Error(`${url} HTTP ${r.status}`);
  return r.json();
}

async function loadData(force=false){
  if(force) toast("최신 데이터 확인 중…");
  if(!app.loaded){
    loadingView.classList.remove("hidden");
    errorView.classList.add("hidden");
  }
  try{
    const [state,config,lastRefresh]=await Promise.all([
      fetchJson("./state-v2.json",force),
      fetchJson("./metrics-v2.json",force),
      fetchJson("./last-refresh.json",force).catch(()=>null),
    ]);
    if(state?.recordCount!==3700 || !Array.isArray(state.records)) throw new Error("3,700종목 상태파일 형식 오류");
    if(config?.metricCount!==9 || !Array.isArray(config.metrics)) throw new Error("9지표 설정파일 형식 오류");

    app.records=state.records;
    app.recordMap=new Map(app.records.map(r=>[String(r.ticker||"").toUpperCase(),r]));
    app.config=config;
    app.lastRefresh=lastRefresh;
    if(!app.appliedFilters){
      app.appliedFilters=makeFilters();
      app.draftFilters=deepClone(app.appliedFilters);
    }
    app.loaded=true;
    headerSub.textContent=`${state.recordCount.toLocaleString()}종목 · ${state.metricCount}지표 · Public V2`;
    loadingView.classList.add("hidden");
    errorView.classList.add("hidden");
    showTab(app.tab,true);
    if(force) toast(heldRecords().length ? "공개 데이터 확인 완료 · 갱신 보류 종목 포함" : "공개 데이터를 다시 읽었습니다.");
  }catch(e){
    console.error(e);
    if(!app.loaded){
      loadingView.classList.add("hidden");
      errorView.classList.remove("hidden");
      $("#errorMessage").textContent=e?.message || "네트워크 연결을 확인해주세요.";
    }else{
      toast("데이터 갱신 실패 · 기존 화면 유지");
    }
  }
}

function hideAll(){
  Object.values(views).forEach(v=>v.classList.add("hidden"));
}
function setNav(tab){
  $$("button[data-tab]",nav).forEach(b=>b.classList.toggle("active",b.dataset.tab===tab));
}
function showTab(tab,rerender=false){
  if(!app.loaded) return;
  app.detailTicker=null;
  app.tab=tab;
  app.visibleRows=120;
  hideAll();
  setNav(tab);
  views[tab].classList.remove("hidden");
  if(tab==="ranking") renderRanking();
  if(tab==="filter") renderFilter();
  if(tab==="favorites") renderFavorites();
  if(tab==="data") renderData();
  window.scrollTo({top:0,behavior:rerender?"auto":"smooth"});
}
function openDetail(ticker){
  const r=app.recordMap.get(String(ticker).toUpperCase());
  if(!r) return;
  app.previousTab=app.tab;
  app.detailTicker=r.ticker;

  // One same-document history entry makes Android back return to the
  // exact list tab instead of closing the WebView activity.
  history.pushState(
    {usv2:"detail",ticker:r.ticker,from:app.previousTab},
    "",
    "#detail="+encodeURIComponent(r.ticker)
  );

  hideAll();
  views.detail.classList.remove("hidden");
  setNav("");
  renderDetail(r);
  window.scrollTo({top:0,behavior:"smooth"});
}

function closeDetail(){
  const target=app.previousTab || "ranking";
  if(app.detailTicker && history.state?.usv2==="detail"){
    history.back();
    return true;
  }
  if(app.detailTicker){
    showTab(target,true);
    return true;
  }
  return false;
}

// Called first by the Android wrapper on the physical/gesture Back action.
window.USV2_NATIVE_BACK=()=>closeDetail();

window.addEventListener("popstate",()=>{
  if(!app.loaded) return;
  if(app.detailTicker){
    const target=app.previousTab || "ranking";
    showTab(target,true);
  }
});

function activeBaseRecords(){
  let rows=app.records;
  const q=app.query.trim().toLowerCase();
  if(q){
    rows=rows.filter(r=>
      String(r.ticker||"").toLowerCase().includes(q) ||
      String(r.company||"").toLowerCase().includes(q)
    );
  }
  if(app.sector!=="ALL") rows=rows.filter(r=>normalizedSector(r)===app.sector);
  if(app.connected==="9") rows=rows.filter(r=>Number(r.numericCount)===9);
  return rows;
}
function currentView(){
  const dir = ["Price_Sales_TTM","Shares_Change_YoY_Pct"].includes(app.sortKey) ? "asc" : "desc";
  return buildView(activeBaseRecords(),{
    filters:app.appliedFilters,
    weights:app.appliedWeights,
    minimumConnected:8,
    sortKey:app.sortKey,
    direction:dir
  });
}
function scoreClass(score){
  if(score>=70) return "green";
  if(score>=55) return "blue";
  return "";
}
function metricChip(r,key){
  return `<span class="metric-chip">${esc(metricLabel(key))} ${esc(metricText(r,key))}</span>`;
}
function stockRow(r,index,withRank=true){
  const fav=app.favorites.has(r.ticker);
  const score=n(r.quantitativeScore,1);
  const rank=withRank ? `<div class="rank-no ${index<3?"top":""}">${index+1}</div>` : "";
  return `
    <div class="stock-row row-hit ${r.refreshHold?"refresh-held":""}" data-open="${esc(r.ticker)}">
      ${rank}
      <div class="stock-main">
        <div class="ticker">${esc(r.ticker)}${r.refreshHold?'<span class="hold-badge">갱신 보류 · 보관값</span>':""}</div>
        <div class="company-line"><span class="company">${esc(r.company || r.ticker)}</span><span class="sector-tag">${esc(normalizedSector(r))}</span></div>
        <div class="metric-chips">
          ${metricChip(r,"Revenue_TTM_YoY_Pct")}
          ${metricChip(r,"Price_Sales_TTM")}
        </div>
        ${r.refreshHold?`<div class="hold-row-note">${esc(holdDates(r))}<br>${esc(holdMetricText(r))}</div>`:""}
      </div>
      <div class="score-box ${scoreClass(r.quantitativeScore)}">${score}</div>
      <button class="star-btn ${fav?"on":""}" type="button" data-fav="${esc(r.ticker)}" aria-label="관심종목">${fav?"★":"☆"}</button>
    </div>`;
}

function renderRanking(){
  const view=currentView();
  const rows=view.rows.slice(0,app.visibleRows);
  const presentSectors=new Set(app.records.map(normalizedSector));
  const sectors=SECTOR_ORDER.filter(s=>presentSectors.has(s));
  const n9=app.records.filter(r=>Number(r.numericCount)===9).length;
  const filterOn=Object.values(app.appliedFilters).filter(f=>f.enabled).length;

  views.ranking.innerHTML=`
    <div class="hero-strip">
      <div><h2>랭킹</h2><p>9지표와 내가 정한 가중치로 계산한 정량 순위</p></div>
      <div class="right-note">필터 ${filterOn}개 적용</div>
    </div>
    ${holdOverview()}
    <div class="search-row">
      <label class="search-box">⌕<input id="searchInput" value="${esc(app.query)}" placeholder="종목명 또는 티커를 검색하세요" autocomplete="off"></label>
    </div>
    <div class="stat-grid">
      <div class="stat-card"><b>3,700</b><span>전체 종목</span></div>
      <div class="stat-card"><b class="green">${n9.toLocaleString()}</b><span>9/9 연결</span></div>
      <div class="stat-card"><b class="blue">${view.totalMatched.toLocaleString()}</b><span>현재 조건 결과</span></div>
    </div>
    <div class="control-row">
      <select id="sortSelect" class="select">
        <option value="score" ${app.sortKey==="score"?"selected":""}>종합점수 높은 순</option>
        ${app.config.metrics.map(m=>`<option value="${m.key}" ${app.sortKey===m.key?"selected":""}>${esc(m.label)} 기준</option>`).join("")}
      </select>
      <select id="sectorSelect" class="select">
        <option value="ALL">전체 섹터</option>
        ${sectors.map(s=>`<option value="${esc(s)}" ${app.sector===s?"selected":""}>${esc(s)}</option>`).join("")}
      </select>
      <select id="connectedSelect" class="select">
        <option value="8" ${app.connected==="8"?"selected":""}>8/9 이상</option>
        <option value="9" ${app.connected==="9"?"selected":""}>9/9만</option>
      </select>
    </div>
    <div class="panel">
      <div class="list-head"><span>순위</span><span>종목</span><span>종합점수</span><span>관심</span></div>
      <div id="rankingRows">
        ${rows.length?rows.map((r,i)=>stockRow(r,i,true)).join(""):`<div class="empty"><strong>조건에 맞는 종목이 없습니다.</strong><span>필터를 완화해보세요.</span></div>`}
      </div>
      ${view.rows.length>app.visibleRows?`<button id="loadMore" class="load-more" type="button">더보기 · ${Math.min(120,view.rows.length-app.visibleRows)}종목</button>`:""}
    </div>`;

  $("#searchInput",views.ranking)?.addEventListener("input",e=>{app.query=e.target.value;app.visibleRows=120;renderRanking();$("#searchInput",views.ranking)?.focus();});
  $("#sortSelect",views.ranking)?.addEventListener("change",e=>{app.sortKey=e.target.value;renderRanking();});
  $("#sectorSelect",views.ranking)?.addEventListener("change",e=>{app.sector=e.target.value;renderRanking();});
  $("#connectedSelect",views.ranking)?.addEventListener("change",e=>{app.connected=e.target.value;renderRanking();});
  $("#loadMore",views.ranking)?.addEventListener("click",()=>{app.visibleRows+=120;renderRanking();});
  wireRows(views.ranking);
}

function filterRow(m){
  const f=app.draftFilters[m.key];
  const w=app.draftWeights[m.key];
  const isRange=f.op==="range";
  return `
    <div class="filter-row" data-key="${m.key}">
      <input class="enable-check" type="checkbox" data-role="enabled" ${f.enabled?"checked":""} aria-label="${esc(m.label)} 필터 사용">
      <div class="filter-label">${esc(m.label)}</div>
      <select class="select" data-role="op" ${isRange?"disabled":""}>
        ${isRange?'<option value="range">범위</option>':`
          <option value=">=" ${f.op===">="?"selected":""}>&gt;=</option>
          <option value="<=" ${f.op==="<="?"selected":""}>&lt;=</option>`}
      </select>
      <div class="filter-value-wrap">
        ${isRange?
          `<div class="range-inputs"><input class="input" data-role="min" type="number" step="0.1" value="${f.min}"><span>~</span><input class="input" data-role="max" type="number" step="0.1" value="${f.max}"></div>`:
          `<input class="input" data-role="value" type="number" step="0.1" value="${f.value}">`
        }
      </div>
      <div class="weight-wrap"><input class="input" data-role="weight" type="number" min="0" max="100" step="1" value="${w}"></div>
    </div>`;
}
function weightTotal(){
  return METRIC_KEYS.reduce((s,k)=>s+Number(app.draftWeights[k]||0),0);
}
function updateWeightUi(){
  const box=$("#weightTotal",views.filter);
  const apply=$("#applyFilters",views.filter);
  if(!box||!apply)return;
  const total=weightTotal();
  box.textContent=`${n(total,1)}%`;
  box.closest(".weight-total")?.classList.toggle("bad",Math.abs(total-100)>.001);
  apply.disabled=Math.abs(total-100)>.001;
}
function renderFilter(){
  const active=Object.values(app.draftFilters).filter(f=>f.enabled).length;
  views.filter.innerHTML=`
    <div class="hero-strip">
      <div><h2>필터 설정</h2><p>지표 조건과 가중치를 같은 줄에서 바로 조절</p></div>
      <div class="right-note">${active}개 지표 필터 사용</div>
    </div>
    <div class="panel filter-panel">
      <div class="weight-total"><div><b>가중치 합계</b><div class="company">종합점수 계산 비중</div></div><strong id="weightTotal">100%</strong></div>
      <div class="filter-grid-head"><span>사용</span><span>지표</span><span>조건</span><span>기준값</span><span>가중치</span></div>
      ${app.config.metrics.map(filterRow).join("")}
      <div class="action-row">
        <button id="clearFilters" class="secondary-btn" type="button">초기화</button>
        <button id="defaultFilters" class="secondary-btn" type="button">기본값</button>
        <button id="applyFilters" class="primary-btn" type="button">적용하기 →</button>
      </div>
    </div>`;

  $$("[data-key]",views.filter).forEach(row=>{
    const key=row.dataset.key;
    $$("[data-role]",row).forEach(el=>{
      el.addEventListener("input",()=>{
        const role=el.dataset.role;
        if(role==="enabled") app.draftFilters[key].enabled=el.checked;
        if(role==="op") app.draftFilters[key].op=el.value;
        if(role==="value") app.draftFilters[key].value=Number(el.value);
        if(role==="min") app.draftFilters[key].min=Number(el.value);
        if(role==="max") app.draftFilters[key].max=Number(el.value);
        if(role==="weight") app.draftWeights[key]=Number(el.value);
        updateWeightUi();
      });
      el.addEventListener("change",()=>el.dispatchEvent(new Event("input")));
    });
  });
  $("#clearFilters",views.filter).addEventListener("click",()=>{
    app.draftFilters=makeFilters();
    app.config.metrics.forEach(m=>app.draftFilters[m.key].enabled=false);
    app.draftWeights={...UI_DEFAULT_WEIGHTS};
    renderFilter();
  });
  $("#defaultFilters",views.filter).addEventListener("click",()=>{
    const enabled=Object.fromEntries(METRIC_KEYS.map(k=>[k,Boolean(app.draftFilters[k]?.enabled)]));
    app.draftFilters=makeFilters();
    METRIC_KEYS.forEach(k=>{app.draftFilters[k].enabled=enabled[k];});
    app.draftWeights={...UI_DEFAULT_WEIGHTS};
    renderFilter();
  });
  $("#applyFilters",views.filter).addEventListener("click",()=>{
    if(!validateWeights(app.draftWeights)){toast("가중치 합계를 100%로 맞춰주세요.");return;}
    app.appliedFilters=deepClone(app.draftFilters);
    app.appliedWeights={...app.draftWeights};
    toast("필터와 가중치를 적용했습니다.");
    showTab("ranking");
  });
  updateWeightUi();
}

function renderFavorites(){
  const base=[...app.favorites].map(t=>app.recordMap.get(t)).filter(Boolean);
  const rows=buildView(base,{filters:makeFilters(),weights:app.appliedWeights,minimumConnected:8,sortKey:"score",direction:"desc"}).rows;
  views.favorites.innerHTML=`
    <div class="hero-strip">
      <div><h2>관심 종목</h2><p>기기에 저장됩니다. 로그인이나 서버가 필요 없습니다.</p></div>
      <div class="right-note">${rows.length}개 저장</div>
    </div>
    ${rows.some(r=>r.refreshHold)?'<div class="refresh-notice"><p>갱신 보류 종목의 지표와 점수는 이전 검증값 기준입니다.</p></div>':""}
    <div class="panel favorite-list">
      ${rows.length?rows.map((r,i)=>stockRow(r,i,false)).join(""):`<div class="empty"><strong>관심 종목이 없습니다.</strong><span>랭킹에서 ☆을 눌러 추가하세요.</span></div>`}
    </div>`;
  wireRows(views.favorites);
}
function wireRows(root){
  if(root.dataset.rowsWired==="1") return;
  root.dataset.rowsWired="1";
  root.addEventListener("click",e=>{
    const fav=e.target.closest("[data-fav]");
    if(fav){
      e.stopPropagation();
      toggleFavorite(fav.dataset.fav);
      if(app.tab==="favorites") renderFavorites(); else renderRanking();
      return;
    }
    const hit=e.target.closest("[data-open]");
    if(hit) openDetail(hit.dataset.open);
  });
}
function toggleFavorite(ticker){
  if(app.favorites.has(ticker)){app.favorites.delete(ticker);toast(`${ticker} 관심종목 해제`);}
  else{app.favorites.add(ticker);toast(`${ticker} 관심종목 추가`);}
  persistFavorites();
}

function renderDetail(r){
  const fav=app.favorites.has(r.ticker);
  const exchange=encodeURIComponent(r.exchange||"NASDAQ");
  const ticker=encodeURIComponent(r.ticker);
  const numeric=Number(r.numericCount||0);
  views.detail.innerHTML=`
    <div class="detail-top">
      <button id="detailBack" class="back-btn" type="button">←</button>
      <div class="detail-id">
        <h2>${esc(r.ticker)}</h2>
        <div class="company">${esc(r.company||r.ticker)}</div>
        <div class="detail-meta">${esc(r.exchange||"")} · ${esc(normalizedSector(r))} ${r.industry?"· "+esc(r.industry):""}</div>
      </div>
      <button id="detailStar" class="detail-star ${fav?"on":""}" type="button">${fav?"★":"☆"}</button>
    </div>

    ${holdDetail(r)}
    <div class="chart-card">
      <iframe class="chart-frame" loading="lazy" referrerpolicy="strict-origin-when-cross-origin"
        src="./chart.html?tvwidgetsymbol=${encodeURIComponent((r.exchange||"NASDAQ")+":"+r.ticker)}"
        title="${esc(r.ticker)} 확인용 차트"></iframe>
      <div class="chart-note"><span>확인용 일봉 차트</span><span>TradingView · 지연 가능</span></div>
    </div>

    <div class="section-title"><h3>핵심 투자 지표</h3><span>${numeric}/9 ${r.refreshHold?"보관값 기준":"연결"}</span></div>
    <div class="metric-grid">
      ${app.config.metrics.map(m=>{
        const c=r.metrics?.[m.key]||{};
        const regression=heldMetrics(r).find(h=>h.key===m.key);
        return `<div class="metric-card ${r.refreshHold?"metric-held":""}">
          <label>${esc(m.label)}</label>
          <b>${esc(metricText(r,m.key))}</b>
          ${r.refreshHold?'<span class="metric-hold-label">이전 검증값</span>':""}
          ${regression?`<span class="metric-regression">N/A 미해결 · ${esc(regression.source || c.source || m.source)}<br>N/A 확인 ${esc(fmtDate(regression.observedAt || r.refreshHold.attemptedAt))}</span>`:""}
          <small>${esc(c.source||m.source)}<br>값 확인 ${esc(fmtDate(c.updatedAt))}</small>
        </div>`;
      }).join("")}
    </div>

    <div class="section-title"><h3>기업 정보</h3><span>Public V2</span></div>
    <div class="company-card">
      <b>${esc(r.company||r.ticker)}</b><br>
      티커 ${esc(r.ticker)}
      ${r.exchange?` · 거래소 ${esc(r.exchange)}`:""}
       · 섹터 ${esc(normalizedSector(r))}
      ${r.industry?`<br>산업 ${esc(r.industry)}`:""}
      <br>정량 데이터와 차트는 서로 독립적으로 동작합니다. 차트 로딩이 실패해도 9지표·랭킹·필터에는 영향을 주지 않습니다.
    </div>`;

  $("#detailBack",views.detail).addEventListener("click",()=>closeDetail());
  $("#detailStar",views.detail).addEventListener("click",()=>{
    toggleFavorite(r.ticker);renderDetail(r);
  });
}

function renderData(){
  const n9=app.records.filter(r=>Number(r.numericCount)===9).length;
  const n8=app.records.filter(r=>Number(r.numericCount)>=8).length;
  const held=heldRecords().length;
  const lr=app.lastRefresh||{};
  const latest=lr.finishedAt || lr.latestSuccessfulRefreshAt;
  views.data.innerHTML=`
    <div class="hero-strip">
      <div><h2>데이터</h2><p>수집 상태와 지표별 갱신 시각을 확인</p></div>
      <div class="right-note">Public V2</div>
    </div>
    <div class="health-card ${held?"health-held":""}"><span class="health-dot"></span><div><strong>${held?`갱신 보류 ${held.toLocaleString()}종목`:"공개 데이터 불러오기 완료"}</strong><span>${held?"이전 검증값을 유지하고 있습니다. 최신 수집값과 다를 수 있습니다.":"앱은 공개 상태파일을 읽기만 합니다."}</span></div></div>
    ${holdOverview()}
    <div class="data-grid">
      <div class="data-card"><label>전체 종목</label><b>3,700</b><small>고정 유니버스</small></div>
      <div class="data-card"><label>최근 배치</label><b>${Number(lr.batchSize||1000).toLocaleString()}종목</b><small>${esc(fmtDate(lr.finishedAt))}</small></div>
      <div class="data-card"><label>자동 갱신</label><b>6시간마다</b><small>하루 4회</small></div>
      <div class="data-card"><label>실행 워커</label><b>${Number(lr.workers||3)}개</b><small>병렬 수집</small></div>
      <div class="data-card"><label>9/9 연결</label><b>${n9.toLocaleString()}</b><small>전체 3,700종목 중${held?" · 보관값 포함":""}</small></div>
      <div class="data-card"><label>8/9 이상</label><b>${n8===3700?"100%":n(n8/37,1)+"%"}</b><small>${n8.toLocaleString()} / 3,700${held?" · 보관값 포함":""}</small></div>
      <div class="data-card"><label>갱신 보류</label><b>${held.toLocaleString()}종목</b><small>현재 상태파일 기준 · 이전 검증값 유지</small></div>
    </div>
    <div class="section-title"><h3>최근 배치 완료</h3><span>${esc(fmtDate(latest))}</span></div>
    <div class="data-refresh-row">
      <div><b>현재 공개 데이터 다시 읽기</b><span>수집 Action은 실행하지 않습니다.</span></div>
      <button id="reloadData" class="secondary-btn" type="button">새로고침</button>
    </div>
    <div class="section-title"><h3>지표별 업데이트 현황</h3><span>9지표</span></div>
    <div class="metric-status-list">
      ${app.config.metrics.map(m=>{
        const u=lr.metricUpdates?.[m.key]?.latestUpdatedAt;
        return `<div class="metric-status-row"><span>${esc(m.label)}</span><span>${esc(fmtDate(u))}</span></div>`;
      }).join("")}
    </div>`;
  $("#reloadData",views.data).addEventListener("click",()=>loadData(true));
}

nav.addEventListener("click",e=>{
  const b=e.target.closest("button[data-tab]");
  if(b) showTab(b.dataset.tab);
});
$("#dataReloadTop").addEventListener("click",()=>loadData(true));
$("#retryButton").addEventListener("click",()=>loadData(true));

if(!history.state?.usv2){
  history.replaceState({usv2:"tab",tab:"ranking"},"",location.pathname+location.search);
}

loadData();
