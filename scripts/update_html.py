"""更新 核企智评_交互演示(3).html — 硬编码数据 → API 调用"""
import pathlib
import re
import sys
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)

ROOT = pathlib.Path(__file__).resolve().parent.parent
HTML = ROOT / "核企智评_交互演示(3).html"

content = HTML.read_text(encoding="utf-8")

# ═══ 1. Scorecards: D1+D3 → D1-D4 ═══
old = (
    '<div class="scorecards">'
    '<div class="scorecard"><span>基本面评分</span><strong id="summaryD1">—</strong><small>/ 100</small></div>'
    '<div class="scorecard"><span>核企信用评分</span><strong id="summaryD3">—</strong><small>/ 100</small></div>'
    '</div>'
)
new = (
    '<div class="scorecards">'
    '<div class="scorecard"><span>行业景气</span><strong id="summaryD1">—</strong><small>/ 100</small></div>'
    '<div class="scorecard"><span>品牌竞争力</span><strong id="summaryD2">—</strong><small>/ 100</small></div>'
    '<div class="scorecard"><span>核企自身信用</span><strong id="summaryD3">—</strong><small>/ 100</small></div>'
    '<div class="scorecard"><span>经销商体系</span><strong id="summaryD4">—</strong><small>/ 100</small></div>'
    '</div>'
)
assert content.count(old) == 1, f"Scorecards: found {content.count(old)}"
content = content.replace(old, new)
print("[OK] Scorecards")

# ═══ 2. Detail grid: add D2/D4 cards + loading ═══
# Find what's between knownDetail and unknownDetail
old2 = (
    '<section id="knownDetail" class="detailgrid">'
    '<article class="card">'
    '<div class="cardhead"><div><span class="kicker">维度一 \xb7 行业景气</span><h2>第一层基本面</h2></div><span class="weight">层内六项指标</span></div>'
    '<div id="basicMetrics" class="metrics"></div>'
    '<div id="basicFormula" class="formula"></div>'
    '</article>'
    '<article class="card">'
    '<div class="cardhead"><div><span class="kicker">维度三</span><h2>核企自身信用</h2></div><span class="weight">主体风险优先</span></div>'
    '<div id="creditMetrics" class="metrics"></div>'
    '<div id="redline" class="redline"></div>'
    '<div id="creditFormula" class="formula"></div>'
    '</article>'
    '</section>'
)
new2 = (
    '<div id="loadingEval" class="hidden" style="margin-top:16px;padding:30px;text-align:center;border:1px solid var(--line);border-radius:13px;background:#fff">'
    '<div class="spinner"></div>'
    '<p style="margin:12px 0 0;color:var(--muted);font-size:11px">评分引擎计算中，请稍候…</p>'
    '</div>'
    '<section id="knownDetail" class="detailgrid">'
    '<article class="card">'
    '<div class="cardhead"><div><span class="kicker">维度一 \xb7 行业景气</span><h2>D1</h2></div><span class="weight">占 15%</span></div>'
    '<div id="basicMetrics" class="metrics"></div>'
    '<div id="basicFormula" class="formula"></div>'
    '</article>'
    '<article class="card">'
    '<div class="cardhead"><div><span class="kicker">维度二 \xb7 品牌竞争力</span><h2>D2</h2></div><span class="weight">占 15%</span></div>'
    '<div id="brandMetrics" class="metrics"></div>'
    '</article>'
    '<article class="card">'
    '<div class="cardhead"><div><span class="kicker">维度三 \xb7 核企自身信用</span><h2>D3</h2></div><span class="weight">占 40%</span></div>'
    '<div id="creditMetrics" class="metrics"></div>'
    '<div id="redline" class="redline"></div>'
    '<div id="creditFormula" class="formula"></div>'
    '</article>'
    '<article class="card">'
    '<div class="cardhead"><div><span class="kicker">维度四 \xb7 经销商体系健康度</span><h2>D4</h2></div><span class="weight">占 30%</span></div>'
    '<div id="dealerMetrics" class="metrics"></div>'
    '</article>'
    '</section>'
)
assert content.count(old2) == 1, f"Detail grid: found {content.count(old2)}"
content = content.replace(old2, new2)
print("[OK] Detail grid")

# ═══ 3. Add companyName to each case + API_BASE ═══
# C01
content = content.replace(
    "const cases=[\n      {id:'C01',core:'华曜智能终端有限公司',dealer:'北辰渠道科技有限公司',industry:'消费电子',d1:94,d3:90,",
    "const API_BASE=window.location.origin;\n      const cases=[\n      {id:'C01',core:'华曜智能终端有限公司',dealer:'北辰渠道科技有限公司',industry:'消费电子',companyName:'华曜智能终端有限公司',"
)
print("[OK] C01")

# C02
content = content.replace(
    "{id:'C02',core:'恒岳智慧家电有限公司',dealer:'盛联商贸有限公司',industry:'智能家电',d1:80,d3:80,",
    "{id:'C02',core:'恒岳智慧家电有限公司',dealer:'盛联商贸有限公司',industry:'智能家电',companyName:'恒岳智慧家电有限公司',"
)
print("[OK] C02")

# C03
content = content.replace(
    "{id:'C03',core:'绿驰储能设备有限公司',dealer:'东南能源渠道有限公司',industry:'储能设备',d1:60,d3:60,",
    "{id:'C03',core:'绿驰储能设备有限公司',dealer:'东南能源渠道有限公司',industry:'储能设备',companyName:'绿驰储能设备有限公司',"
)
print("[OK] C03")

# C04
content = content.replace(
    "{id:'C04',core:'新港工业材料有限公司',dealer:'海岳分销有限公司',industry:'工业材料',d1:53,d3:67,",
    "{id:'C04',core:'新港工业材料有限公司',dealer:'海岳分销有限公司',industry:'工业材料',companyName:'新港工业材料有限公司',"
)
print("[OK] C04")

# C05
content = content.replace(
    "{id:'C05',core:'远辰精密化工有限公司',dealer:'鑫达供应链有限公司',industry:'精密化工',d1:87,d3:0,",
    "{id:'C05',core:'远辰精密化工有限公司',dealer:'鑫达供应链有限公司',industry:'精密化工',companyName:'远辰精密化工有限公司',"
)
print("[OK] C05")

# ═══ 4. Replace openDetail function ═══
start_marker = "function openDetail(item){"
end_marker = "function toast(text){"
start_idx = content.find(start_marker)
end_idx = content.find(end_marker)
assert start_idx >= 0, "openDetail not found!"
assert end_idx >= 0, "toast not found!"

old_open = content[start_idx:end_idx]

new_open = """function openDetail(item){
  current=item;
  $('#listPage').classList.add('hidden');$('#detailPage').classList.remove('hidden');
  $('#detailTitle').textContent=item.core+' \\xd7 '+item.dealer;
  $('#detailSub').textContent='\\u4f01\\u4e1a\\u5173\\u7cfb\\u7f16\\u53f7\\uff1a'+item.id+' \\xb7 \\u6570\\u636e\\u6765\\u6e90\\uff1a'+(item.source||'\\u6848\\u4f8b\\u5e93');
  $('#summaryStatus').textContent='\\u8bc4\\u5206\\u5f15\\u64ce\\u8ba1\\u7b97\\u4e2d\\u2026';
  $('#summaryText').textContent=item.summary||'\\u6b63\\u5728\\u8ba1\\u7b97\\u8bc4\\u5206\\uff0c\\u8bf7\\u7a0d\\u5019';
  $('#summaryD1').textContent='\\u2026';$('#summaryD2').textContent='\\u2026';
  $('#summaryD3').textContent='\\u2026';$('#summaryD4').textContent='\\u2026';
  $('#knownDetail').classList.add('hidden');$('#loadingEval').classList.remove('hidden');
  $('#unknownDetail').classList.add('hidden');window.scrollTo({top:0,behavior:'smooth'});
  if(item.companyName){
    fetch(API_BASE+'/api/evaluate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({company_name:item.companyName})})
    .then(function(r){return r.json()})
    .then(function(data){
      if(data.error){$('#summaryStatus').textContent='\\u8ba1\\u7b97\\u5f02\\u5e38';$('#summaryText').textContent=data.error;clearScores();$('#loadingEval').classList.add('hidden');return;}
      renderApiResult(data,item);
    })
    .catch(function(err){$('#summaryStatus').textContent='\\u8bc4\\u5206\\u670d\\u52a1\\u6682\\u4e0d\\u53ef\\u7528';$('#summaryText').textContent='\\u540e\\u7aef\\u8bc4\\u5206\\u5f15\\u64ce\\u6682\\u4e0d\\u53ef\\u7528\\uff0c\\u8bf7\\u7a0d\\u540e\\u91cd\\u8bd5\\u3002';clearScores();$('#loadingEval').classList.add('hidden');});
  } else {renderFallback(item);}
}
function clearScores(){['D1','D2','D3','D4'].forEach(function(d){$('#summary'+d).textContent='\\u2014';});}
function renderApiResult(data,item){
  var ds=data.dimension_scores||{};
  $('#summaryStatus').textContent=data.redline_triggered?'\\u4e00\\u7968\\u5426\\u51b3':(data.rating==='A'||data.rating==='B')?'\\u6821\\u9a8c\\u901a\\u8fc7':'\\u9700\\u4eba\\u5de5\\u590d\\u6838';
  $('#summaryText').textContent=data.rating==='D'?'\\u7ea2\\u7ebf\\u89e6\\u53d1\\u4e00\\u7968\\u5426\\u51b3\\uff0c\\u8bc4\\u7ea7\\u9501\\u5b9a\\u4e3aD':'\\u7efc\\u5408\\u8bc4\\u5206 '+Math.round(data.total_score)+'/'+data.rating+'\\u7ea7';
  $('#summaryD1').textContent=Math.round(ds.D1||0);$('#summaryD2').textContent=Math.round(ds.D2||0);
  $('#summaryD3').textContent=Math.round(ds.D3||0);$('#summaryD4').textContent=Math.round(ds.D4||0);
  $('#loadingEval').classList.add('hidden');$('#knownDetail').classList.remove('hidden');$('#unknownDetail').classList.add('hidden');
  var dd=data.dimension_details||{};
  renderDimMetrics('basicMetrics',dd.D1);renderDimMetrics('brandMetrics',dd.D2);
  renderDimMetrics('creditMetrics',dd.D3);renderDimMetrics('dealerMetrics',dd.D4);
  var rd=data.redline_details||{};$('#redline').className='redline'+(data.redline_triggered?' bad':'');
  var ck=rd.checks||{};var ks=Object.keys(ck);
  if(ks.length){$('#redline').innerHTML='<h3>\\u7ea2\\u7ebf\\u68c0\\u67e5</h3><div class="redlineGrid">'+ks.map(function(k){var c=ck[k];return '<span class="'+(c.triggered?'baditem':'')+'">'+(c.triggered?'! ':'\\u2713 ')+(c.label||k)+'</span>';}).join('')+'</div>';}
  else{$('#redline').innerHTML='<h3>\\u7ea2\\u7ebf\\u68c0\\u67e5</h3><p style="padding:7px;color:var(--green);font-size:10px">\\u2713 \\u672a\\u89e6\\u53d1\\u7ea2\\u7ebf</p>';}
  var formula='\\u7efc\\u5408\\u5206 = D1('+Math.round(ds.D1||0)+')\\xd715% + D2('+Math.round(ds.D2||0)+')\\xd715% + D3('+Math.round(ds.D3||0)+')\\xd740% + D4('+Math.round(ds.D4||0)+')\\xd730% = '+Math.round(data.total_score);
  $('#basicFormula').textContent=formula;$('#creditFormula').textContent=data.redline_triggered?'\\u7ea2\\u7ebf\\u89e6\\u53d1\\uff0cD3\\u5f52\\u96f6\\uff0c\\u8bc4\\u7ea7\\u9501\\u5b9aD':'\\u7efc\\u5408\\u8bc4\\u5206\\u516c\\u5f0f\\u5982\\u4e0a';
}
function renderDimMetrics(cid,dd){
  var el=$('#'+cid);if(!el)return;
  if(!dd||!dd.details||Object.keys(dd.details).length===0){el.innerHTML='<div class="metric"><div><b>\\u65e0\\u660e\\u7ec6\\u6570\\u636e</b><p>\\u8be5\\u7ef4\\u5ea6\\u6682\\u65e0\\u6307\\u6807\\u7ea7\\u660e\\u7ec6</p></div></div>';return;}
  el.innerHTML=Object.values(dd.details).map(function(d){
    var cv=(d.company_value!=null)?d.company_value:'N/A';var sc=(d.score!=null)?d.score:'\\u2014';
    var nm=d.name||'\\u6307\\u6807';var bw=(typeof sc==='number'&&sc>=0)?Math.min(100,Math.max(0,sc)):0;
    return '<div class="metric"><div><b>'+nm+'</b><p>\\u516c\\u53f8\\u503c: '+cv+' | \\u884c\\u4e1a\\u57fa\\u51c6: '+(d.benchmark_value||'N/A')+'</p></div><div class="metricScore"><span class="bar"><i style="width:'+bw+'%"></i></span><strong>'+(typeof sc==='number'?Math.round(sc):sc)+'</strong></div></div>';
  }).join('');
}
function renderFallback(item){
  var s=item.status;
  $('#summaryStatus').textContent=s==='\\u901a\\u8fc7'?'\\u6821\\u9a8c\\u901a\\u8fc7':s==='\\u4e0d\\u901a\\u8fc7'?'\\u4e00\\u7968\\u5426\\u51b3':'\\u9700\\u4eba\\u5de5\\u590d\\u6838';
  $('#summaryText').textContent=item.summary||'';
  $('#summaryD1').textContent=item.d1||'\\u2014';$('#summaryD2').textContent='\\u2014';
  $('#summaryD3').textContent=item.d3||'\\u2014';$('#summaryD4').textContent='\\u2014';
  $('#loadingEval').classList.add('hidden');$('#knownDetail').classList.remove('hidden');
  if(item.basic){
    $('#basicMetrics').innerHTML=item.basic.map(metricHtml).join('');
    $('#creditMetrics').innerHTML=item.credit.map(metricHtml).join('');
    $('#brandMetrics').innerHTML='<div class="metric"><div><b>\\u79bb\\u7ebf\\u6a21\\u5f0f</b><p>D2\\u548cD4\\u4ec5\\u5728\\u7ebf\\u53ef\\u7528</p></div></div>';
    $('#dealerMetrics').innerHTML='<div class="metric"><div><b>\\u79bb\\u7ebf\\u6a21\\u5f0f</b><p>D2\\u548cD4\\u4ec5\\u5728\\u7ebf\\u53ef\\u7528</p></div></div>';
  }
  var bad=item.id==='C05';
  $('#redline').className='redline'+(bad?' bad':'');
  if(item.red){$('#redline').innerHTML='<h3>\\u53f8\\u6cd5\\u4fe1\\u7528\\u4e0e\\u8d44\\u6599\\u68c0\\u67e5</h3><div class="redlineGrid">'+item.red.map(function(r,i){return '<span class="'+(bad&&i===3?'baditem':'')+'">'+(bad&&i===3?'! ':'\\u2713 ')+r+'</span>';}).join('')+'</div>';}
}
"""

content = content[:start_idx] + new_open + content[end_idx:]
print("[OK] openDetail replaced")

HTML.write_text(content, encoding="utf-8")
print("[DONE] HTML 更新完成！")
