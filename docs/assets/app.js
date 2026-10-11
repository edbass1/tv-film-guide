(function(){
"use strict";
var G = window.GUIDE;
var KINDS = [["films","FILM"],["docs","DOCUMENTARI"]];
var VIEWS = [["prime","Prima serata"],["clou","Il clou"],["genre","Per genere"],["rating","Per voto"],["all","Tutti per orario"]];
var CC = {DE:"Germania",AT:"Austria",CH:"Svizzera",FR:"Francia",IT:"Italia",UK:"Regno Unito",ES:"Spagna"};
var FROM = {de:"dal tedesco",fr:"dal francese",es:"dallo spagnolo",en:"dall'inglese"};
var COUNTRIES = [["IT","Canali italiani"],["CH","Canali svizzeri"],["DE","Canali tedeschi"],["AT","Canali austriaci"],["FR","Canali francesi"],["UK","Canali inglesi"],["ES","Canali spagnoli"]];
var hidden = {};
try { hidden = JSON.parse(localStorage.getItem("tvcc")||"{}")||{}; } catch(e){ hidden = {}; }
function ccOn(cc){ return !hidden[cc]; }
// un programma resta visibile se il suo canale (o una replica) è di un paese selezionato
function visible(i){
  if (ccOn(i.cc)) {
    if (!i.also) return i;
    var o = Object.assign({}, i); o.also = i.also.filter(function(a){ return ccOn(a.cc||i.cc); }); return o;
  }
  var alt = (i.also||[]).filter(function(a){ return a.cc && ccOn(a.cc); });
  if (!alt.length) return null;
  var o2 = Object.assign({}, i, {ch:alt[0].ch, cc:alt[0].cc, b:alt[0].b, e:alt[0].e||i.e, prime:alt[0].prime, dual:alt[0].dual, also:alt.slice(1)});
  return o2;
}
var st = {day:0, kind:"films", view:"prime", genre:null};
try { Object.assign(st, JSON.parse(sessionStorage.getItem("tvst2")||"{}")); } catch(e){}
location.hash.replace(/^#/,"").split("&").forEach(function(kv){ var p=kv.split("="); if(p[0]==="day") st.day=parseInt(p[1],10)||0; else if(p[0]==="kind"||p[0]==="view") st[p[0]]=p[1]; });
if (!/^(films|docs)$/.test(st.kind)) st.kind="films";
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
// salta i giorni già passati (se la pagina non è stata aggiornata da poco)
var todayIso = new Date(Date.now()-5*3600e3).toISOString().substr(0,10);
var first = 0; while (first < G.days.length-1 && G.days[first].date < todayIso) first++;
var DAYS = G.days.slice(first);
if (st.day >= DAYS.length) st.day = 0;

function save(){ sessionStorage.setItem("tvst2", JSON.stringify(st)); }
function btns(el, list, cur, onpick){
  el.innerHTML = "";
  list.forEach(function(x){
    var b=document.createElement("button"); b.type="button";
    b.innerHTML = x[1]; b.setAttribute("aria-pressed", String(x[0]===cur));
    b.onclick=function(){ onpick(x[0]); window.scrollTo(0, document.getElementById("main").offsetTop-10); }; el.appendChild(b);
  });
}
function card(i){
  var now = Date.now(), past = new Date(i.e).getTime() < now;
  var title = i.it || i.t;
  var h = '<article class="card'+(i.clou?' clou':'')+(past?' past':'')+'">';
  h += '<div class="when"><span class="time">'+hhmm(i.b)+'</span><span class="chan">'+esc(i.ch)+'</span>';
  if (i.b.substr(0,10)!==DAYS[st.day].date) h += '<span class="date">'+dshort(i.b)+'</span>';
  if (past) h += '<span class="date">(finito)</span>';
  h += '</div>';
  h += '<h3 class="title">'+(i.u?'<a href="'+esc(i.u)+'" target="_blank" rel="noopener">'+esc(title)+'</a>':esc(title));
  if (i.dual) h += ' <span class="b dual" title="Canale con doppio audio (lingua originale)">DOPPIO AUDIO</span>';
  h += '</h3>';
  var alts=[];
  if (i.it && i.it!==i.t) alts.push("In onda come: "+esc(i.t)+(i.its==="auto"?' <em class="mt">(titolo: traduzione automatica)</em>':""));
  if (i.o && i.o!==i.t && i.o!==i.it) alts.push("Titolo originale: "+esc(i.o));
  alts.forEach(function(a){ h+='<p class="alt">'+a+'</p>'; });
  if (i.sub && i.sub!==i.t) h += '<p class="sub">'+esc(i.sub)+'</p>';
  h += '<div class="badges">';
  if (i.r) h += '<a class="b imdb" href="https://www.imdb.com/title/'+esc(i.id)+'/" target="_blank" rel="noopener">IMDb '+i.r.toFixed(1)+'</a>';
  else if (i.lv) h += '<span class="b lv" title="Voto La Vanguardia">Voto '+i.lv.toFixed(1)+'</span>';
  if (i.g) h += '<span class="b gen">'+esc(i.g)+'</span>';
  if (i.y) h += '<span class="b gen">'+i.y+'</span>';
  if (i.dur) h += '<span class="b gen">'+i.dur+' min</span>';
  if (i.clou) h += '<span class="b clou">★ CLOU</span>';
  h += '<span class="b cc">'+esc(CC[i.cc]||i.cc)+'</span>';
  h += '</div>';
  if (i.d) h += '<p class="desc">'+esc(i.d)+(i.da?' <em class="mt">(traduzione automatica '+esc(FROM[i.dl||i.lang]||"")+')</em>':'')+'</p>';
  if (i.also && i.also.length) h += '<p class="also">Anche: '+i.also.map(function(a){return esc(a.ch)+' '+dshort(a.b)+' '+hhmm(a.b)+(a.dual?' (doppio audio)':'');}).join(" · ")+'</p>';
  return h + '</article>';
}
function grid(list){
  if (!list.length) return '<p class="empty">Nessun programma trovato.</p>';
  return '<div class="grid">'+list.map(card).join("")+'</div>';
}
function byScore(a,b){ return (b.clou-a.clou)||((b.score||0)-(a.score||0))||a.b.localeCompare(b.b); }
function render(){
  save();
  var D = DAYS[st.day];
  var V = {};
  ["films","docs"].forEach(function(k){ V[k] = D[k].map(visible).filter(Boolean); });
  var cbox = document.getElementById("countries");
  if (!cbox.dataset.done){
    cbox.dataset.done = "1";
    COUNTRIES.forEach(function(c){
      var l = document.createElement("label"); l.className = "cc-opt";
      l.innerHTML = '<input type="checkbox" value="'+c[0]+'"'+(ccOn(c[0])?' checked':'')+'> <span>'+c[1]+'</span> <b class="n"></b>';
      l.querySelector("input").onchange = function(ev){
        if (ev.target.checked) delete hidden[c[0]]; else hidden[c[0]] = 1;
        localStorage.setItem("tvcc", JSON.stringify(hidden)); render();
      };
      cbox.appendChild(l);
    });
    var all = document.createElement("button"); all.type="button"; all.className="cc-all"; all.textContent="Tutti i paesi";
    all.onclick = function(){ hidden = {}; localStorage.setItem("tvcc","{}"); Array.prototype.forEach.call(cbox.querySelectorAll("input"), function(x){x.checked=true;}); render(); };
    cbox.appendChild(all);
  }
  Array.prototype.forEach.call(cbox.querySelectorAll("label.cc-opt"), function(l){
    var cc = l.querySelector("input").value;
    var n = D[st.kind].filter(function(i){ return i.cc===cc; }).length;
    l.querySelector(".n").textContent = "("+n+")";
    l.classList.toggle("off", !ccOn(cc));
  });
  btns(document.getElementById("days"), DAYS.map(function(d,k){return [k, esc(d.label)+'<small>'+esc(d.long)+'</small>'];}), st.day, function(k){st.day=k;st.genre=null;render();});
  btns(document.getElementById("kinds"), KINDS.map(function(k){return [k[0], k[1]+' ('+V[k[0]].length+')'];}), st.kind, function(k){st.kind=k;st.genre=null;render();});
  btns(document.getElementById("views"), VIEWS.map(function(v){return [v[0], (st.kind==="docs"&&v[0]==="genre")?"Per argomento":v[1]];}), st.view, function(v){st.view=v;st.genre=null;render();});
  var onlyDual=document.getElementById("onlyDual").checked, showPast=document.getElementById("showPast").checked;
  var now=Date.now();
  var items = V[st.kind].filter(function(i){
    if (onlyDual && !i.dual) return false;
    if (!showPast && new Date(i.e).getTime() < now) return false;
    return true;
  });
  var kname = st.kind==="docs"?"documentari":"film";
  var h="";
  if (st.view==="prime"){
    var p=items.filter(function(i){return i.prime;}).sort(byScore);
    h+='<h2 class="sec">Prima serata – '+esc(D.long)+'</h2><p class="hint">'+kname+' che iniziano tra le '+G.prime.from+' e le '+G.prime.to+' (Spagna fino alle '+G.prime_es.to+'). Prima i più importanti.</p>'+grid(p);
  } else if (st.view==="clou"){
    var c=items.filter(function(i){return i.clou;}).sort(function(a,b){return (b.score||0)-(a.score||0);});
    h+='<h2 class="sec">Il clou – '+esc(D.long)+'</h2><p class="hint">'+(st.kind==="films"?'I film più importanti: voto IMDb alto con molti voti, o film molto conosciuti.':'I documentari più importanti: voto IMDb alto, o canali di qualità in prima serata.')+'</p>'+grid(c.slice(0,60));
  } else if (st.view==="genre"){
    var groups={};
    items.forEach(function(i){
      var g=i.g||"Altro"; (groups[g]=groups[g]||[]).push(i);
      if (st.kind==="films" && i.y && i.y<=G.classic) (groups["Classici"]=groups["Classici"]||[]).push(i);
    });
    var names=Object.keys(groups).sort(function(a,b){ if(a==="Classici")return -1; if(b==="Classici")return 1; if(a==="Altro")return 1; if(b==="Altro")return -1; return groups[b].length-groups[a].length;});
    if (!st.genre || !groups[st.genre]) st.genre = names.filter(function(n){return n!=="Classici";})[0]||names[0]||null;
    h+='<h2 class="sec">'+(st.kind==="docs"?"Per argomento":"Per genere")+' – '+esc(D.long)+'</h2>';
    if (st.kind==="films") h+='<p class="hint">Classici = film usciti fino al '+G.classic+' (compaiono anche nel loro genere).</p>';
    h+='<div class="genres">';
    names.forEach(function(n){ h+='<button type="button" data-g="'+esc(n)+'" aria-pressed="'+(n===st.genre)+'">'+esc(n)+' ('+groups[n].length+')</button>'; });
    h+='</div>';
    if (st.genre) h+=grid(groups[st.genre].slice().sort(function(a,b){return a.b.localeCompare(b.b);}));
  } else if (st.view==="rating"){
    var r=items.filter(function(i){return i.r||i.lv;}).sort(function(a,b){return ((b.r||b.lv)-(a.r||a.lv))||((b.v||0)-(a.v||0));});
    h+='<h2 class="sec">Per voto – '+esc(D.long)+'</h2><p class="hint">Ordinati per voto IMDb, dal più alto (per i film spagnoli senza IMDb: voto La Vanguardia). Senza voto: '+(items.length-r.length)+'.</p>'+grid(r);
  } else {
    h+='<h2 class="sec">Tutti per orario – '+esc(D.long)+'</h2>'+grid(items.slice().sort(function(a,b){return a.b.localeCompare(b.b);}));
  }
  var m=document.getElementById("main"); m.innerHTML=h;
  Array.prototype.forEach.call(m.querySelectorAll(".genres button"), function(b){ b.onclick=function(){ st.genre=b.getAttribute("data-g"); render(); }; });
}
document.getElementById("onlyDual").onchange=render;
document.getElementById("showPast").onchange=render;
render();
})();
