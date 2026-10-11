(function(){
"use strict";
var G = window.GUIDE;
var KINDS = [["films","FILM"],["docs","DOCUMENTARI"],["es","FILM SPAGNA"]];
var VIEWS = [["prime","Prima serata"],["clou","Il clou"],["genre","Per genere"],["rating","Per voto"],["all","Tutti per orario"]];
var st = {day:0, kind:"films", view:"prime", genre:null};
try { Object.assign(st, JSON.parse(sessionStorage.getItem("tvst")||"{}")); } catch(e){}
// link diretti, es. index.html#kind=docs&view=clou&day=1
location.hash.replace(/^#/,"").split("&").forEach(function(kv){ var p=kv.split("="); if(p[0]==="day") st.day=parseInt(p[1],10)||0; else if(p[0]==="kind"||p[0]==="view") st[p[0]]=p[1]; });
var fs = parseInt(localStorage.getItem("tvfs")||"0",10);
function applyFs(){ document.documentElement.style.setProperty("--fs", (22+fs*3)+"px"); }
applyFs();
document.getElementById("fontPlus").onclick=function(){ if(fs<6){fs++;localStorage.setItem("tvfs",fs);applyFs();} };
document.getElementById("fontMinus").onclick=function(){ if(fs>-2){fs--;localStorage.setItem("tvfs",fs);applyFs();} };

function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];}); }
function hhmm(iso){ return iso.substr(11,5); }
var WD=["dom","lun","mar","mer","gio","ven","sab"];
function dshort(iso){ var d=new Date(iso.substr(0,10)+"T12:00:00"); return WD[d.getDay()]+" "+d.getDate()+"/"+(d.getMonth()+1); }

var gd = new Date(G.generated);
document.getElementById("updated").textContent = "Aggiornato: " + gd.toLocaleString("it-IT",{weekday:"long",day:"numeric",month:"long",hour:"2-digit",minute:"2-digit"});
if (st.day >= G.days.length) st.day = 0;

function save(){ sessionStorage.setItem("tvst", JSON.stringify(st)); }
function btns(el, list, cur, onpick){
  el.innerHTML = "";
  list.forEach(function(x){
    var b=document.createElement("button"); b.type="button";
    b.innerHTML = x[1]; b.setAttribute("aria-pressed", String(x[0]===cur));
    b.onclick=function(){ onpick(x[0]); }; el.appendChild(b);
  });
}
function card(i, showDate){
  var now = Date.now(), past = new Date(i.end).getTime() < now;
  var title = i.it || i.title;
  var h = '<article class="card'+(i.clou?' clou':'')+(past?' past':'')+'">';
  h += '<div class="when"><span class="time">'+hhmm(i.begin)+'</span><span class="chan">'+esc(i.ch)+'</span>';
  if (showDate || i.begin.substr(0,10)!==G.days[st.day].date) h += '<span class="date">'+dshort(i.begin)+'</span>';
  if (past) h += '<span class="date">(finito)</span>';
  h += '</div>';
  h += '<h3 class="title">'+(i.url?'<a href="'+esc(i.url)+'" target="_blank" rel="noopener">'+esc(title)+'</a>':esc(title))+'</h3>';
  var alts=[];
  if (i.it && i.it!==i.title) alts.push("In onda come: "+esc(i.title)+(i.it_src==="auto"?" <em>(titolo italiano: traduzione automatica)</em>":""));
  if (i.orig && i.orig!==i.title && i.orig!==i.it) alts.push("Originale: "+esc(i.orig));
  alts.forEach(function(a){ h+='<p class="alt">'+a+'</p>'; });
  if (i.sub && i.sub!==i.title) h += '<p class="sub">'+esc(i.sub)+'</p>';
  h += '<div class="badges">';
  if (i.dual==="sì") h += '<span class="b dual" title="Canale con doppio audio / lingua originale">DOPPIO AUDIO</span>';
  else if (i.dual==="teleboy") h += '<span class="b dual tb" title="Segnalato da Teleboy per questo programma">DOPPIO AUDIO</span>';
  if (i.imdb) h += '<span class="b imdb">IMDb '+i.imdb.toFixed(1)+'</span>';
  if (i.lv) h += '<span class="b lv" title="Voto La Vanguardia">Voto '+i.lv.toFixed(1)+'</span>';
  if (i.genre) h += '<span class="b gen">'+esc(i.genre)+'</span>';
  if (i.year) h += '<span class="b gen">'+i.year+'</span>';
  if (i.dur) h += '<span class="b gen">'+i.dur+' min</span>';
  if (i.clou) h += '<span class="b clou">★ CLOU</span>';
  h += '</div>';
  if (i.desc) h += '<p class="desc">'+esc(i.desc)+'</p>';
  if (i.also && i.also.length) h += '<p class="also">Anche: '+i.also.map(function(a){return esc(a.ch)+' '+dshort(a.begin)+' '+hhmm(a.begin)+(a.dual?' (doppio audio)':'');}).join(" · ")+'</p>';
  return h + '</article>';
}
function grid(list, showDate){
  if (!list.length) return '<p class="empty">Nessun programma trovato.</p>';
  return '<div class="grid">'+list.map(function(i){return card(i, showDate);}).join("")+'</div>';
}
function render(){
  save();
  var D = G.days[st.day];
  btns(document.getElementById("days"), G.days.map(function(d,k){return [k, esc(d.label)+'<small>'+esc(d.long)+'</small>'];}), st.day, function(k){st.day=k;st.genre=null;render();});
  btns(document.getElementById("kinds"), KINDS.map(function(k){return [k[0], k[1]+' ('+D[k[0]].length+')'];}), st.kind, function(k){st.kind=k;st.genre=null;render();});
  btns(document.getElementById("views"), VIEWS.map(function(v){return [v[0], (st.kind==="docs"&&v[0]==="genre")?"Per argomento":v[1]];}), st.view, function(v){st.view=v;render();});
  var onlyDual=document.getElementById("onlyDual").checked, showPast=document.getElementById("showPast").checked;
  var now=Date.now();
  var items = D[st.kind].filter(function(i){
    if (onlyDual && !i.dual) return false;
    if (!showPast && new Date(i.end).getTime() < now) return false;
    return true;
  });
  var kname = st.kind==="docs"?"documentari":"film";
  var P = st.kind==="es"?G.prime_es:G.prime;
  var h="";
  if (st.view==="prime"){
    var p=items.filter(function(i){return i.prime;});
    p.sort(function(a,b){ return (b.clou-a.clou)||((b.score||0)-(a.score||0))||a.begin.localeCompare(b.begin); });
    h+='<h2 class="sec">Prima serata – '+esc(D.long)+'</h2><p class="hint">'+kname+' che iniziano tra le '+P.from+' e le '+P.to+'. Prima i più importanti.</p>'+grid(p);
  } else if (st.view==="clou"){
    var c=items.filter(function(i){return i.clou;}).sort(function(a,b){return (b.score||0)-(a.score||0);});
    h+='<h2 class="sec">Il clou – '+esc(D.long)+'</h2><p class="hint">I '+kname+' più importanti della giornata'+(st.kind==="films"?' (voto IMDb alto e film molto conosciuti)':st.kind==="docs"?' (voto alto o canali di qualità in prima serata)':' (voto alto)')+'.</p>'+grid(c.slice(0,40));
  } else if (st.view==="genre"){
    var groups={}; items.forEach(function(i){ var g=i.genre||"Altro"; (groups[g]=groups[g]||[]).push(i); });
    var names=Object.keys(groups).sort(function(a,b){return groups[b].length-groups[a].length;});
    if (!st.genre || !groups[st.genre]) st.genre = names[0]||null;
    h+='<h2 class="sec">'+(st.kind==="docs"?"Per argomento":"Per genere")+' – '+esc(D.long)+'</h2><div class="genres">';
    names.forEach(function(n){ h+='<button type="button" data-g="'+esc(n)+'" aria-pressed="'+(n===st.genre)+'">'+esc(n)+' ('+groups[n].length+')</button>'; });
    h+='</div>';
    if (st.genre) h+=grid(groups[st.genre]);
  } else if (st.view==="rating"){
    var r=items.filter(function(i){return i.imdb||i.lv;}).sort(function(a,b){return ((b.imdb||b.lv)-(a.imdb||a.lv))||((b.votes||0)-(a.votes||0));});
    h+='<h2 class="sec">Per voto – '+esc(D.long)+'</h2><p class="hint">'+(st.kind==="es"?'Voto di La Vanguardia (IMDb non disponibile per questa fonte).':'Ordinati per voto IMDb, dal più alto.')+' Senza voto: '+(items.length-r.length)+'.</p>'+grid(r);
  } else {
    h+='<h2 class="sec">Tutti per orario – '+esc(D.long)+'</h2>'+grid(items.slice().sort(function(a,b){return a.begin.localeCompare(b.begin);}));
  }
  if (st.kind==="es" && !D.es.length) h+='<p class="hint">La Vanguardia pubblica solo circa 3 giorni di programmazione.</p>';
  var m=document.getElementById("main"); m.innerHTML=h;
  Array.prototype.forEach.call(m.querySelectorAll(".genres button"), function(b){ b.onclick=function(){ st.genre=b.getAttribute("data-g"); render(); }; });
}
document.getElementById("onlyDual").onchange=render;
document.getElementById("showPast").onchange=render;
render();
})();
