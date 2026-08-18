
const $=s=>document.querySelector(s);
const files=[];
let stream=null;

function show(id,btn){
  ["dashboard","register","users","logs","items"].forEach(x=>document.getElementById(x).classList.toggle("hidden",x!==id));
  document.querySelectorAll(".side").forEach(x=>x.classList.remove("active")); if(btn)btn.classList.add("active");
  if(id==="users")loadUsers(); if(id==="logs")loadLogs(); if(id==="items")loadItems(); if(id==="dashboard")loadAnalytics();
}
async function get(u,o){const r=await fetch(u,o);const d=await r.json();if(!r.ok)throw Error(d.error||"Request failed");return d}
async function stats(){const d=await get("/api/stats");["total","present","entries","exits","alerts"].forEach(k=>$("#"+k).textContent=d[k])}
function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"}[c]))}
async function loadUsers(){const a=await get("/api/users");$("#usersBody").innerHTML=a.length?a.map(x=>`<tr><td><b>${esc(x.name)}</b></td><td>${esc(x.student_id)}</td><td><span class="tag">${esc(x.role)}</span></td><td>${esc(x.department)}</td><td>📸 ${x.photo_count||1}</td><td>${esc(x.created_at)}</td></tr>`).join(""):`<tr><td colspan="6" class="empty">No people registered yet.</td></tr>`}
async function loadLogs(){const a=await get("/api/attendance");$("#attBody").innerHTML=a.length?a.map(x=>`<tr><td><b>${esc(x.name)}</b></td><td>${esc(x.student_id)}</td><td><span class="action ${x.action.toLowerCase()}">${x.action}</span></td><td>${esc(x.timestamp)}</td></tr>`).join(""):`<tr><td colspan="4" class="empty">No attendance yet.</td></tr>`;const b=await get("/api/alerts");$("#alertBody").innerHTML=b.length?b.map(x=>`<tr><td><span class="tag danger">${esc(x.alert_type)}</span></td><td>${esc(x.message)}</td><td>${esc(x.timestamp)}</td></tr>`).join(""):`<tr><td colspan="3" class="empty">No alerts.</td></tr>`}
async function loadItems(){const a=await get("/api/items");$("#itemsBody").innerHTML=a.length?a.map(x=>`<tr><td>${esc(x.item_code)}</td><td><b>${esc(x.title)}</b></td><td><span class="tag">${esc(x.status)}</span></td></tr>`).join(""):`<tr><td colspan="3" class="empty">No items added.</td></tr>`}
async function loadAnalytics(){
 const d=await get("/api/analytics");
 const days=[...Array(7)].map((_,i)=>{let x=new Date();x.setDate(x.getDate()-(6-i));return x.toISOString().slice(0,10)});
 const max=Math.max(1,...d.daily.map(x=>+x.count));
 $("#chart").innerHTML=days.map(day=>{const en=d.daily.find(x=>x.day===day&&x.action==="ENTRY")?.count||0, ex=d.daily.find(x=>x.day===day&&x.action==="EXIT")?.count||0;return `<div class="bar-col"><div class="bars"><i style="height:${en/max*100}%"></i><i class="exitbar" style="height:${ex/max*100}%"></i></div><small>${day.slice(5)}</small></div>`}).join("");
 $("#roles").innerHTML=d.roles.length?d.roles.map(x=>`<div class="role-row"><span>${esc(x.role)}</span><b>${x.count}</b><div><i style="width:${Math.min(100,x.count/Math.max(1,d.roles[0].count)*100)}%"></i></div></div>`).join(""):`<div class="empty">No data yet.</div>`;
 $("#recent").innerHTML=d.recent.length?d.recent.map(x=>`<div class="activity-row"><span class="avatar">${esc(x.name).charAt(0).toUpperCase()}</span><div><b>${esc(x.name)}</b><small>${esc(x.student_id)} • ${esc(x.timestamp)}</small></div><span class="action ${x.action.toLowerCase()}">${x.action}</span></div>`).join(""):`<div class="empty">No activity yet.</div>`;
}
async function refreshAll(){await stats();await loadAnalytics()}
stats();loadAnalytics();setInterval(refreshAll,5000);

/* Registration: webcam capture + multiple uploads */
function renderPreviews(){
 $("#photoCount").textContent=`${files.length} / 8`;
 $("#preview").innerHTML=files.map((f,i)=>`<div class="thumb"><img src="${f.url}"><button type="button" onclick="removePhoto(${i})">×</button><small>${f.source}</small></div>`).join("");
}
function addFile(file,source){
 if(files.length>=8)return;
 if(!file.type.startsWith("image/"))return;
 files.push({file,url:URL.createObjectURL(file),source});renderPreviews();
}
window.removePhoto=i=>{URL.revokeObjectURL(files[i].url);files.splice(i,1);renderPreviews()}
$("#photoFiles").onchange=e=>{[...e.target.files].slice(0,8-files.length).forEach(f=>addFile(f,"Upload"));e.target.value=""};

$("#startCam").onclick=async()=>{
 try{
  if(stream){stream.getTracks().forEach(t=>t.stop());stream=null;$("#startCam").textContent="▶ Start Camera";$("#captureBtn").disabled=true;return}
  stream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:720},height:{ideal:480},facingMode:"user"},audio:false});
  $("#regVideo").srcObject=stream;$("#startCam").textContent="■ Stop Camera";$("#captureBtn").disabled=false;
 }catch(e){$("#regMsg").textContent="Camera access failed. You can still upload photos."}
};
$("#captureBtn").onclick=()=>{
 if(!stream||files.length>=8)return;
 const v=$("#regVideo"),c=$("#regCanvas");c.width=v.videoWidth;c.height=v.videoHeight;c.getContext("2d").drawImage(v,0,0);
 c.toBlob(blob=>addFile(new File([blob],`camera_${Date.now()}.jpg`,{type:"image/jpeg"}),"Camera"),"image/jpeg",.92);
};

$("#reg").onsubmit=async e=>{
 e.preventDefault(); if(!files.length){$("#regMsg").textContent="Please capture or upload at least one photo.";return}
 const fd=new FormData(e.target);fd.delete("photo");files.forEach(x=>fd.append("photos",x.file));
 $("#regMsg").textContent="Processing face photos…";
 try{const d=await get("/api/register",{method:"POST",body:fd});$("#regMsg").textContent="✓ "+d.message;e.target.reset();files.splice(0).forEach(x=>URL.revokeObjectURL(x.url));renderPreviews();await stats()}catch(x){$("#regMsg").textContent="✕ "+x.message}
};
$("#itemForm").onsubmit=async e=>{e.preventDefault();const o=Object.fromEntries(new FormData(e.target));try{const d=await get("/api/items",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(o)});$("#itemMsg").textContent="✓ "+d.message;e.target.reset();loadItems();stats()}catch(x){$("#itemMsg").textContent="✕ "+x.message}};
