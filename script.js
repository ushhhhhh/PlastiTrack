// Dataset: grams of plastic per item (approx. averages) + alternatives
var ITEMS=[
{id:"bottle",name:"Plastic water bottle (500ml)",g:12,def:7,alt:"Reusable steel/copper bottle",cut:0.95,tip:"Carry a refillable bottle; refill at water stations."},
{id:"bag",name:"Plastic carry bag",g:6,def:5,alt:"Cloth / jute bag",cut:0.9,tip:"Keep a foldable cloth bag in your backpack."},
{id:"straw",name:"Plastic straw",g:0.5,def:3,alt:"Steel / bamboo straw or skip it",cut:1,tip:"Just sip directly or use a steel straw."},
{id:"cutlery",name:"Disposable cutlery set",g:4,def:2,alt:"Personal steel cutlery set",cut:0.95,tip:"Keep a spoon/fork set in your bag."},
{id:"box",name:"Takeaway plastic container",g:15,def:2,alt:"Steel tiffin / own container",cut:0.9,tip:"Ask for food in your own tiffin box."},
{id:"cup",name:"Disposable plastic/coated cup",g:10,def:4,alt:"Reusable mug / kulhad",cut:0.9,tip:"Use your own mug at the canteen or tea stall."},
{id:"wrap",name:"Snack wrapper / sachet",g:3,def:6,alt:"Bulk buying, paper or refill packs",cut:0.6,tip:"Buy larger packs or loose snacks to cut wrappers."}
];
var CO2_PER_KG=3.0; // approx. kg CO2e per kg plastic (assumption)
var box=document.getElementById("inputs");
ITEMS.forEach(function(i){
 var d=document.createElement("div");d.className="row";
 d.innerHTML='<div>'+i.name+'<small>~'+i.g+' g each</small></div><input type="number" min="0" id="q_'+i.id+'" value="'+i.def+'">';
 box.appendChild(d);
});
function f(n,d){return n.toFixed(d===undefined?1:d)}
document.getElementById("go").onclick=function(){
 var rows=ITEMS.map(function(i){
  var q=Math.max(0,parseFloat(document.getElementById("q_"+i.id).value)||0);
  return {i:i,q:q,wk:q*i.g};
 });
 var wk=rows.reduce(function(a,r){return a+r.wk},0);
 var yr=wk*52/1000, co2=yr*CO2_PER_KG;
 // eco score: 100 at 0 g/week, falls to 0 at 1000 g/week
 var score=Math.max(0,Math.round(100-wk/10));
 document.getElementById("sW").textContent=f(wk,0);
 document.getElementById("sY").textContent=f(yr);
 document.getElementById("sC").textContent=f(co2);
 document.getElementById("sS").textContent=score;
 var max=Math.max.apply(null,rows.map(function(r){return r.wk}))||1;
 document.getElementById("bars").innerHTML=rows.map(function(r){
  return '<div style="margin:8px 0"><div style="display:flex;justify-content:space-between"><span>'+r.i.name+'</span><span>'+f(r.wk,0)+' g/wk</span></div><div class="bar" style="width:'+(r.wk/max*100)+'%"></div></div>';
 }).join("");
 // Recommendation engine: rank by plastic that can be saved
 var rec=rows.filter(function(r){return r.wk>0}).map(function(r){
  r.save=r.wk*r.i.cut;return r}).sort(function(a,b){return b.save-a.save});
 var saveYr=rec.reduce(function(a,r){return a+r.save},0)*52/1000;
 document.getElementById("rP").textContent=f(saveYr);
 document.getElementById("rC").textContent=f(saveYr*CO2_PER_KG);
 var html="";
 rec.forEach(function(r,idx){
  html+='<div class="alt'+(idx==0?' hl':'')+'"><b>'+r.i.name+'</b>'+(idx==0?'<span class="tag">Biggest impact</span>':'')+
  '<br>Switch to: <b>'+r.i.alt+'</b> (saves ~'+f(r.save*52/1000)+' kg plastic/yr)<br><small>'+r.i.tip+'</small></div>';
 });
 document.getElementById("alts").innerHTML=html||"<p>No single-use plastic entered. Great job!</p>";
 document.getElementById("top").textContent=rec.length?
  "Start with your biggest saving: replacing "+rec[0].i.name.toLowerCase()+" alone cuts "+f(rec[0].save*52/1000)+" kg of plastic a year.":"";
 document.getElementById("out").classList.remove("hide");
 document.getElementById("rec").classList.remove("hide");
 document.getElementById("out").scrollIntoView({behavior:"smooth"});
};